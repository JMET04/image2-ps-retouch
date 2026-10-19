"""Bind native inspection evidence to the exact file that was opened."""
import hashlib
from pathlib import Path


def fingerprint(path):
    path=Path(path).resolve(strict=True)
    before=path.stat()
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):
            digest.update(block)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('File changed while collecting evidence: '+str(path))
    return dict(path=str(path),size_bytes=after.st_size,sha256=digest.hexdigest())


def verify_psd_proof(path,proof,expected_size):
    path=Path(path).resolve(strict=True)
    if proof.get('evidence_version')!=2:
        raise ValueError('New acceptance requires native inspection bound to the exact PSD; legacy history is preserved')
    if Path(proof.get('psd','')).resolve()!=path or proof.get('psd_fingerprint')!=fingerprint(path):
        raise ValueError('PSD inspection does not match the current file')
    if proof.get('actual_native_open') is not True or proof.get('size')!=list(expected_size):
        raise ValueError('Native inspection canvas differs from final JPEG')
    if 'SIXTEEN' not in proof.get('bits','') or proof.get('profile')!='sRGB IEC61966-2.1':
        raise ValueError('Expected 16-bit sRGB editable PSD')
    layers=proof.get('layers',[])
    if proof.get('layer_count')!=len(layers) or len(layers)<2 or not any(x.get('kind')=='LayerKind.SMARTOBJECT' for x in layers):
        raise ValueError('Editable layers and original smart object were not verified')
    return True
