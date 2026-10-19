"""Lay out real originals/references/accepted PS renders without photo edits."""
from pathlib import Path
import argparse,json,math
import fitz
from PIL import Image,ImageCms,ImageDraw,ImageFont
from reference_match import display_rgb,sha


def accepted_rows(root):
    batch=json.loads((root/'批次状态.json').read_text(encoding='utf-8-sig'))
    rows=[p for p in batch['photos'] if p.get('accepted') and p.get('status')=='accepted_redo']
    if len(rows)!=batch['target'] or batch['completed']!=batch['target']:
        raise ValueError(f"Final comparison requires all {batch['target']} accepted; actual {len(rows)}")
    if len({str(Path(p['source']).resolve()) for p in rows})!=batch['target']:
        raise ValueError('Duplicate sources do not count toward a complete collection')
    inputs={r['name']:r for r in json.loads((root/'核对'/'36张输入来源.json').read_text(encoding='utf-8-sig'))}
    checked=[]
    for item in rows:
        name=Path(item['source']).stem
        qa=json.loads(Path(item['qa']).read_text(encoding='utf-8-sig'))
        if qa.get('visual_acceptance')!='accepted' or not qa.get('visual_notes'):
            raise ValueError('Actual visual acceptance missing: '+name)
        if 'SIXTEEN' not in qa.get('native_psd_inspection',''):
            raise ValueError('Actual native 16-bit PSD inspection missing: '+name)
        source=Path(item['source']); original=Path(inputs[name]['input'])
        reference=Path(item['new_reference']); final=Path(item['final_jpg']); psd=Path(item['final_psd'])
        if not psd.is_file() or psd.stat().st_size==0:
            raise ValueError('Editable PSD missing: '+name)
        if sha(source)!=item['source_sha256'] or sha(original)!=inputs[name]['input_sha256']:
            raise ValueError('Original or verified baseline changed: '+name)
        if sha(reference)!=item['new_reference_sha256'] or sha(final)!=qa['final_sha256']:
            raise ValueError('Reference or accepted final changed: '+name)
        checked.append({'name':name,'source':str(source),'source_sha256':item['source_sha256'],'original':str(original),'reference':str(reference),'final':str(final),'psd':str(psd),'qa':item['qa']})
    return checked


def comparison_sheet(row,number,total,destination):
    images=[display_rgb(row[k],generated=(k=='reference')) for k in ['original','reference','final']]
    width,margin,gap=2880,36,24
    col=(width-2*margin-2*gap)//3
    frame_height=min(1380,math.ceil(max(col*im.height/im.width for im in images)))
    height=180+frame_height+100
    sheet=Image.new('RGB',(width,height),'#111820');draw=ImageDraw.Draw(sheet)
    font=lambda size:ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc',size)
    draw.text((margin,25),f"{number:02d} / {total} · {row['name']} · 第二版",font=font(40),fill='#edf3f7')
    draw.text((margin,83),'原图 → Image2 生成参考 → Photoshop 原像素精修',font=font(24),fill='#b8c6d0')
    raw=Path(row['source']).suffix.lower() not in ['.jpg','.jpeg']
    labels=['原图 · RAW 解码基线' if raw else '原图 · 相机 JPEG','Image2 · 实际生成参考','PS · 已验收精修']
    records=[]
    for i,(im,label,key) in enumerate(zip(images,labels,['original','reference','final'])):
        x=margin+i*(col+gap)
        draw.text((x+(col-draw.textlength(label,font=font(30)))/2,133),label,font=font(30),fill='#edf3f7')
        draw.rectangle((x,180,x+col-1,180+frame_height-1),fill='#080d12')
        preview=im.copy();preview.thumbnail((col,frame_height),Image.Resampling.LANCZOS)
        px=x+(col-preview.width)//2;py=180+(frame_height-preview.height)//2
        sheet.paste(preview,(px,py))
        text=f'来源尺寸 {im.width} × {im.height}'
        draw.text((x+(col-draw.textlength(text,font=font(22)))/2,190+frame_height),text,font=font(22),fill='#bac8d3')
        records.append({'role':key,'path':row[key],'sha256':sha(row[key]),'native_display_size':list(im.size),'preview_box':[px,py,preview.width,preview.height]})
        preview.close();im.close()
    draw.text((margin,height-40),'完整画框等比展示；裁切与水平校正差异保留。生成参考像素没有进入 PS 成片。',font=font(22),fill='#b8c6d0')
    if destination.exists():raise FileExistsError(destination)
    srgb=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    sheet.save(destination,quality=96,subsampling=0,icc_profile=srgb);sheet.close()
    return records,[width,height]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('root',type=Path)
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args();root=args.root.resolve()
    rows=accepted_rows(root)  # Gate runs before output folders or files are created.
    if args.check_only:
        print(json.dumps({'eligible':True,'accepted':len(rows)},ensure_ascii=False));return
    output=root/'三版对比';pdf=root/'36张重修三版对比图册.pdf';index=root/'三版对比目录.md';manifest=root/'核对'/'第二版三版对比核对.json'
    if output.exists() or any(p.exists() for p in [pdf,index,manifest]):
        raise FileExistsError('Preserve prior comparisons; choose a fresh revision root')
    output.mkdir();doc=fitz.open();records=[]
    for number,row in enumerate(rows,1):
        dest=output/f"{number:02d}_{row['name']}_原图_Image2_PS.jpg"
        columns,size=comparison_sheet(row,number,len(rows),dest)
        page=doc.new_page(width=842,height=842*size[1]/size[0]);page.insert_image(page.rect,filename=str(dest))
        records.append(dict(row,number=number,columns=columns,comparison=str(dest),comparison_sha256=sha(dest)))
    doc.set_metadata({'title':'第二版 · 原图 / Image2 / PS · 36张对比','author':'Codex'})
    doc.save(pdf,garbage=4,deflate=True);doc.close()
    for row in records:
        for column in row['columns']:
            if sha(column['path'])!=column['sha256']:raise RuntimeError('A layout input changed')
    link=lambda p:str(p).replace('\\','/')
    lines=['# 第二版三版对比','','完整36张已验收精修，固定从左到右：原图 → 实际Image2生成参考 → PS精修。','',f'[查看36页对比图册]({link(pdf)})','','RAW原图列使用已核实的原生PS解码基线；三列按各自完整画框等比缩放，保留真实构图差异。','']
    for row in records:
        lines.extend([f"## {row['number']:02d} · {row['name']}",'',f"![三版对比]({link(row['comparison'])})",'',f"[原始文件]({link(row['source'])}) · [原图展示来源]({link(row['original'])}) · [Image2生成图]({link(row['reference'])}) · [PS成片]({link(row['final'])}) · [可编辑PSD]({link(row['psd'])})",''])
    index.write_text('\n'.join(lines),encoding='utf-8')
    manifest.write_text(json.dumps({'count':len(records),'layout':['original','reference','final'],'method':'Read-only authentic file layout, source-aware sRGB display, full-frame proportional reduction; no photo grading or generated PS pixels.','inputs_unchanged':True,'pdf':str(pdf),'index':str(index),'photos':records,'visual_layout_review':'pending'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'count':len(records),'pdf':str(pdf),'index':str(index)},ensure_ascii=False))


if __name__=='__main__':main()
