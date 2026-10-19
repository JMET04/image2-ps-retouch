"""Export actual Photoshop selection alpha as diagnostic PNGs, never photo input.

Requires an already running idle Photoshop. Uses the same native mask engine as
retouching. A grayscale preview is evidence of feather and contour coverage;
the geometry overlay alone cannot demonstrate either.
"""
import argparse
import json
from pathlib import Path

from artifact_evidence import fingerprint
from native_guard import NativeGuard, IDLE_PROBE, atomic_json, disk_preflight
from photo_annotations import compile_annotations, read_json
from project_session import check_session


def make_script(compiled, region_ids, outputs):
    payload = dict(canvas=compiled['canvas'], regions=[compiled['regions'][i] for i in region_ids],
                   outputs=[str(p) for p in outputs])
    engine = Path(__file__).with_name('annotation_masks.jsx').read_text('utf-8')
    return engine + '\nvar MASK_PROBE=' + json.dumps(payload, ensure_ascii=True) + ';\n' + r'''
(function(){
  if(app.documents.length!==0)throw new Error('Mask diagnosis requires zero documents');
  var oldDialogs=app.displayDialogs,oldUnits=app.preferences.rulerUnits,doc=null;
  app.displayDialogs=DialogModes.NO;app.preferences.rulerUnits=Units.PIXELS;
  try{
    var black=new SolidColor();black.rgb.red=0;black.rgb.green=0;black.rgb.blue=0;
    var white=new SolidColor();white.rgb.red=255;white.rgb.green=255;white.rgb.blue=255;
    for(var i=0;i<MASK_PROBE.regions.length;i++){
      var w=MASK_PROBE.canvas[0],h=MASK_PROBE.canvas[1];
      doc=app.documents.add(UnitValue(w,'px'),UnitValue(h,'px'),72,'Diagnostic mask',NewDocumentMode.RGB,DocumentFill.WHITE);
      doc.selection.selectAll();doc.selection.fill(black,ColorBlendMode.NORMAL,100,false);doc.selection.deselect();
      PhotoAnnotationMasks.apply(doc,MASK_PROBE.regions[i],MASK_PROBE.canvas);
      doc.selection.fill(white,ColorBlendMode.NORMAL,100,false);doc.selection.deselect();
      doc.saveAs(new File(MASK_PROBE.outputs[i]),new PNGSaveOptions(),true,Extension.LOWERCASE);
      doc.close(SaveOptions.DONOTSAVECHANGES);doc=null;
    }
    return 'Exported '+MASK_PROBE.regions.length+' actual native selection masks';
  }finally{
    if(doc){try{doc.close(SaveOptions.DONOTSAVECHANGES);}catch(ignore){}}
    app.displayDialogs=oldDialogs;app.preferences.rulerUnits=oldUnits;
  }
}());'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('annotations',type=Path)
    parser.add_argument('output_dir',type=Path)
    parser.add_argument('regions',nargs='+')
    args=parser.parse_args()
    if not 1<=len(args.regions)<=3 or len(set(args.regions))!=len(args.regions):
        parser.error('Inspect one to three distinct regions per native call')
    admission=check_session(args.annotations,required_seconds=300)
    compiled=compile_annotations(read_json(args.annotations))
    if any(i not in compiled['regions'] for i in args.regions):parser.error('Unknown region')
    if compiled['canvas'][0]*compiled['canvas'][1]>20_100_000:parser.error('Diagnostic canvas exceeds tested budget')
    # IDs are metadata, never paths. Numbered outputs cannot escape output_dir.
    root=args.output_dir.resolve()
    outputs=[root/f'mask_{i+1}.png' for i in range(len(args.regions))]
    proof=root/'native-mask-proof.json'
    if root.exists():raise FileExistsError('Use a fresh diagnostic directory; inspect existing results before repeating')
    disk_preflight(dict(output_base=str(root/'mask')))
    script=make_script(compiled,args.regions,outputs)
    root.mkdir(parents=True)
    with NativeGuard() as guard:
        guard.call(IDLE_PROBE,timeout=30,identity={'operation':'mask_inspection_idle'})
        raw=guard.call(script,timeout=120,identity={'operation':'native_mask_inspection','annotations':str(args.annotations.resolve()),'output_dir':str(root)})
        report=dict(purpose='Actual Photoshop grayscale selection diagnostics only; never photograph pixels',
            annotation_digest=compiled['annotation_digest'],canvas=compiled['canvas'],
            session_admission=admission,photoshop_version=raw['version'],result=raw['result'],
            outputs=[dict(region_id=i,**fingerprint(p)) for i,p in zip(args.regions,outputs)])
        atomic_json(proof,report)
        report['normal_idle_quit']=guard.call({'operation':'quit_idle'},timeout=30,identity={'operation':'normal_quit_after_mask_inspection'})
        atomic_json(proof,report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
