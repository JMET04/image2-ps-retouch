"""Decode a RAW for focus inspection only; never a final retouched photograph."""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--module-dir', type=Path, help='Optional isolated rawpy installation')
    args = p.parse_args()
    if args.module_dir:
        sys.path.insert(0, str(args.module_dir.resolve(strict=True)))
    import numpy as np
    import rawpy
    from PIL import Image, ImageCms

    source = args.source.resolve(strict=True)
    if source.suffix.lower() not in {'.cr2', '.dng', '.nef', '.arw', '.cr3'}:
        raise ValueError('Completed original RAW required')
    output = args.output.resolve()
    report_path = output.with_suffix('.inspection.json')
    if output == source or output.exists() or report_path.exists():
        raise FileExistsError('Use fresh inspection output paths')
    if output.suffix.lower() != '.png':
        raise ValueError('Inspection output must be PNG')
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    with rawpy.imread(str(source)) as raw:
        sizes = raw.sizes._asdict()
        sensor = raw.raw_image_visible
        saturated = float(np.mean(sensor >= raw.white_level))
        rgb = raw.postprocess(use_camera_wb=True, use_auto_wb=False,
                              no_auto_bright=True, output_bps=8,
                              output_color=rawpy.ColorSpace.sRGB)
        record = {'purpose': 'focus inspection only; not retouch, not Photoshop baseline',
                  'source': str(source), 'source_sha256': before,
                  'decoder': f'rawpy {rawpy.__version__}', 'raw_sizes': sizes,
                  'inspection_size': [rgb.shape[1], rgb.shape[0]],
                  'settings': {'camera_white_balance': True, 'auto_bright': False,
                               'output_color': 'sRGB', 'output_bits': 8, 'resize': False},
                  'sensor_saturated_fraction': saturated,
                  'warning': 'Decoder/color rendering differs from Photoshop. Inspect subject focus; do not use global clipping to reject snow or specular highlights.'}
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError('Original changed during inspection')
    output.parent.mkdir(parents=True, exist_ok=True)
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    Image.fromarray(rgb).save(output, icc_profile=profile)
    record['original_unchanged'] = True
    record['inspection'] = str(output)
    report_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'inspection': str(output), 'size': record['inspection_size'],
                      'original_unchanged': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
