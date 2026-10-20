"""Admit an immutable, natively inspected PSD while retaining its original source."""
from pathlib import Path
from artifact_evidence import fingerprint
from photo_annotations import read_json, sha


def validate_revision(spec, source):
    if not isinstance(spec, dict) or set(spec) != {'psd', 'execution', 'inspection'}:
        raise ValueError('Revision needs PSD, successful execution and actual native inspection')
    psd=Path(spec['psd']).resolve(strict=True)
    if psd.suffix.lower() != '.psd':
        raise ValueError('Revision input must be an editable PSD')
    execution=Path(spec['execution']).resolve(strict=True)
    inspection=Path(spec['inspection']).resolve(strict=True)
    receipt, proof=read_json(execution), read_json(inspection)
    current=fingerprint(psd)
    if not (receipt.get('evidence_version') == 2 and receipt.get('original_unchanged') is True
            and receipt.get('source_sha256') == sha(source) and receipt.get('saved_psd') is True):
        raise ValueError('Revision execution does not bind the unchanged original and saved PSD')
    previous_recipe=Path(receipt['recipe']).resolve(strict=True)
    if sha(previous_recipe) != receipt['recipe_fingerprint']['sha256']:
        raise ValueError('Revision recipe changed since native execution')
    if Path(read_json(previous_recipe)['source']).resolve() != Path(source).resolve():
        raise ValueError('Revision belongs to a different original')
    outputs=receipt.get('output_fingerprints', [])
    if not any(Path(x['path']).resolve() == psd and x['sha256'] == current['sha256'] for x in outputs):
        raise ValueError('Revision PSD is not the saved native output')
    if not (proof.get('actual_native_open') is True
            and proof.get('psd_fingerprint', {}).get('sha256') == current['sha256']
            and Path(proof.get('psd', '')).resolve() == psd
            and proof.get('bits') == 'BitsPerChannelType.SIXTEEN'
            and proof.get('profile') == 'sRGB IEC61966-2.1'
            and any(x.get('kind') == 'LayerKind.SMARTOBJECT' for x in proof.get('layers', []))):
        raise ValueError('Revision needs matching RGB16 sRGB native PSD proof and original smart object')
    size=proof.get('size')
    if not isinstance(size,list) or len(size)!=2 or not all(type(x) is int and x>0 for x in size):
        raise ValueError('Invalid native revision canvas')
    return {'psd':str(psd),'execution':str(execution),'inspection':str(inspection),
            'psd_sha256':current['sha256'],'canvas':size,'layer_count':proof['layer_count'],
            'execution_sha256':sha(execution),'inspection_sha256':sha(inspection)}
