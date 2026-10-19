"""Compact, read-only recovery inventory; never starts or retries Photoshop."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
from native_guard import atomic_json
from project_session import check_session, SessionStopped


def read(path):return json.loads(Path(path).read_text('utf-8-sig'))


def inspect(project):
    root=Path(project).resolve(strict=True)
    batch=root/'重修第二版';manifest=batch/'批次状态.json'
    data=read(manifest);photos=data['photos'];pending=[];missing=[]
    accepted=sum(p.get('accepted') is True for p in photos)
    for photo in photos:
        name=Path(photo['source']).stem
        if photo.get('accepted'):
            for key in ('final_psd','final_jpg','qa'):
                if not photo.get(key) or not Path(photo[key]).is_file():missing.append(dict(photo=name,field=key))
            continue
        receipts=[]
        for path in (batch/'迭代').glob(name+'_match_r*_execution.json'):
            match=re.fullmatch(re.escape(name)+r'_match_r(\d+)_execution.json',path.name)
            if match:
                report=read(path)
                if report.get('original_unchanged') is True:receipts.append((int(match[1]),path,report))
        latest=max(receipts,key=lambda p:p[0]) if receipts else None
        candidates=[]
        for path in (batch/'配方').glob(name+'_match_r*.json'):
            match=re.fullmatch(re.escape(name)+r'_match_r(\d+)\.json',path.name)
            if match and (latest is None or int(match[1])>latest[0]) and not Path(str(read(path)['output_base'])+'_execution.json').exists():
                candidates.append((int(match[1]),path))
        row=dict(photo=name,state=photo.get('status'),next_action='Review saved outputs before native submission')
        if latest:
            row.update(latest_saved_round=latest[0],receipt=str(latest[1]),
                jpeg=str(batch/'迭代'/f'{name}_match_r{latest[0]}.jpg'),
                normal_quit=latest[2].get('normal_idle_quit',{}).get('status','legacy_unknown'))
        if candidates:row['unexecuted_recipe']=str(max(candidates,key=lambda p:p[0])[1])
        final_receipts=[]
        for path in (batch/'成片').glob(name+'_redo_v2_r*_execution.json'):
            match=re.fullmatch(re.escape(name)+r'_redo_v2_r(\d+)([^\\/]*)_execution.json',path.name)
            if match:
                report=read(path)
                if report.get('original_unchanged') is True and report.get('saved_psd') is True:
                    final_receipts.append((int(match[1]),path,report))
        if final_receipts:
            final=max(final_receipts,key=lambda p:(p[0],p[1].stat().st_mtime_ns))
            base=final[1].with_name(final[1].name.removesuffix('_execution.json'))
            row['saved_final_candidate']=dict(round=final[0],receipt=str(final[1]),
                jpeg=str(base.with_suffix('.jpg')),psd=str(base.with_suffix('.psd')),
                files_present=base.with_suffix('.jpg').is_file() and base.with_suffix('.psd').is_file(),
                normal_quit=final[2].get('normal_idle_quit',{}).get('status','legacy_unknown'))
            row['next_action']='Review saved final and native proof before any resubmission'
        pending.append(row)
    native_path=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'CodexPhotoRetouch/native-state.json'
    native=read(native_path) if native_path.is_file() else {}
    try:admission=check_session(root,0)
    except SessionStopped as exc:admission=dict(decision='stopped',reason=str(exc))
    return dict(authority=str(manifest),completed=accepted,total=len(photos),
        count_consistent=data.get('completed')==accepted,missing_accepted_files=missing,
        output_free_gib=round(shutil.disk_usage(root).free/1024**3,2),
        native_state=dict(path=str(native_path),status=native.get('status'),identity=native.get('identity')),
        session=admission,pending=pending,
        scope='Inventory only; process state and visual acceptance still require actual checks')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project',type=Path);parser.add_argument('--out',type=Path)
    args=parser.parse_args();report=inspect(args.project)
    if args.out:atomic_json(args.out,report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
