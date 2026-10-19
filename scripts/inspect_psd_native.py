"""Open a finished PSD in Photoshop and record actual editable structure."""
from pathlib import Path
import sys,json
from native_guard import NativeGuard,IDLE_PROBE,atomic_json
from project_session import check_session
from artifact_evidence import fingerprint, verify_psd_proof

def main():
    source=Path(sys.argv[1]).resolve(strict=True)
    output=Path(sys.argv[2]).resolve()
    if output.exists(): raise FileExistsError(output)
    session_admission=check_session(source, required_seconds=300)
    before=fingerprint(source)
    jsx="""(function(){
    if(app.documents.length!==0)throw new Error('Inspect only at zero documents');
    var old=app.displayDialogs,doc=null;
    app.displayDialogs=DialogModes.NO;
    try{
      doc=app.open(new File(PATH));
      var rows=[doc.width.as('px')+'',doc.height.as('px')+'',doc.bitsPerChannel+'',doc.colorProfileName,doc.layers.length+''];
      for(var i=0;i<doc.layers.length;i++){var l=doc.layers[i];rows.push(l.name+'\\t'+l.kind+'\\t'+l.visible+'\\t'+l.opacity);}
      return rows.join('\\n');
    }finally{if(doc)doc.close(SaveOptions.DONOTSAVECHANGES);app.displayDialogs=old;}
    }());""".replace('PATH',json.dumps(str(source),ensure_ascii=True))
    with NativeGuard() as guard:
        guard.call(IDLE_PROBE,timeout=30,identity={'operation':'inspect_idle'})
        raw=guard.call(jsx,timeout=120,identity={'operation':'actual_psd_inspection','psd':str(source)})
    lines=raw['result'].splitlines()
    after=fingerprint(source)
    if before!=after: raise ValueError('PSD changed during native inspection')
    report=dict(evidence_version=2,psd_fingerprint=after,psd=str(source),photoshop_version=raw['version'],actual_native_open=True,session_admission=session_admission,
                size=[int(float(lines[0])),int(float(lines[1]))],bits=lines[2],profile=lines[3],
                layer_count=int(lines[4]),layers=[dict(zip(['name','kind','visible','opacity'],line.split('\t'))) for line in lines[5:]])
    verify_psd_proof(source,report,report['size'])
    atomic_json(output,report);print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__': main()
