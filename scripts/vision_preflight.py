"""Bind observed defects and reference instructions before admitting a recipe."""
from datetime import datetime
from pathlib import Path
from photo_annotations import read_json, sha


def validate_preflight(path, source, reference):
    path = Path(path).resolve(strict=True)
    data = read_json(path)
    if data.get('schema_version') != 1 or data.get('method') != 'chatgpt_vision':
        raise ValueError('Vision preflight must record actual model observation')
    if Path(data['source']['path']).resolve()!=source or data['source']['sha256']!=sha(source):
        raise ValueError('Preflight belongs to another source')
    if not data.get('subject') or not data.get('visual_hierarchy') or not data.get('observed_key_light'):
        raise ValueError('Preflight needs subject, hierarchy and observed light')
    views = data.get('views_actually_reviewed', [])
    if not views or any(not Path(v['path']).is_file() or sha(v['path'])!=v['sha256'] for v in views):
        raise ValueError('Preflight observation image changed or missing')
    defects = data.get('defects')
    if not isinstance(defects,list):
        raise ValueError('Preflight must explicitly list defects, including an empty list')
    for defect in defects:
        for key in ('id','observation','location','classification','decision','reason','reference_instruction','acceptance'):
            if not isinstance(defect.get(key),str) or not defect[key].strip():
                raise ValueError('Each observed defect needs a decision and testable acceptance')
        if defect['decision'] not in {'repair','crop','tone','retain'}:
            raise ValueError('Unknown defect decision')
    ref = data.get('new_reference', {})
    actual_ref = Path(reference['path']).resolve()
    if Path(ref['path']).resolve()!=actual_ref or ref['sha256']!=sha(actual_ref):
        raise ValueError('Preflight must bind the actual new reference')
    if datetime.fromisoformat(data['diagnosed_at']) > datetime.fromisoformat(ref['generated_at']):
        raise ValueError('Diagnosis must precede reference generation')
    if not ref.get('visual_comparison'):
        raise ValueError('New reference needs an actual comparison to the diagnosis')
    return {'path':str(path),'sha256':sha(path),'defect_ids':[d['id'] for d in defects],
            'reference_sha256':ref['sha256'],'acceptance':'pending native visual review'}
