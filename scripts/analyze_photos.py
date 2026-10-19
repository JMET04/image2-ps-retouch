"""Read-only technical triage of downloaded originals or Photoshop baseline JPEGs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps


def inspect(path: Path) -> dict:
    with Image.open(path) as im:
        size = im.size
        profile = bool(im.info.get('icc_profile'))
        exif = im.getexif()
        oriented = ImageOps.exif_transpose(im).convert('RGB')
        oriented_size = oriented.size
        a = np.asarray(oriented)
    sample = cv2.resize(a, (min(1400, a.shape[1]), max(1, round(a.shape[0] * min(1400, a.shape[1]) / a.shape[1]))))
    lum = cv2.cvtColor(sample, cv2.COLOR_RGB2GRAY)
    # Metrics are diagnostics, not exposure recoverability or aesthetic verdicts.
    return {
        'file': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'native_size': list(size), 'oriented_size': list(oriented_size), 'embedded_profile': profile,
        'camera': str(exif.get(272, '')), 'captured_at': str(exif.get(306, '')),
        'luminance_percentiles': np.percentile(lum, [0, 1, 5, 50, 95, 99, 100]).round(2).tolist(),
        'near_white_fraction': round(float(np.mean(np.all(sample >= 250, axis=2))), 6),
        'near_black_fraction': round(float(np.mean(np.all(sample <= 5, axis=2))), 6),
        'clipped_channel_fraction': [round(float(np.mean(sample[:, :, i] >= 254)), 6) for i in range(3)],
        'laplacian_variance_1400px': round(float(cv2.Laplacian(lum, cv2.CV_64F).var()), 3),
        'review_required': ['100% subject focus', 'key highlight recoverability', 'composition', 'subject clarity'],
        'warning': 'Do not automatically reject bright snow, reflections, intentional silhouettes, shallow depth of field, or low-texture sky using these statistics.'
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('photos', nargs='+', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    records = []
    for path in args.photos:
        try:
            records.append(inspect(path))
        except Exception as exc:
            records.append({'file': str(path), 'error': str(exc), 'status': 'unreadable_pending_review'})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'inspected': len(records), 'errors': sum('error' in r for r in records), 'report': str(args.out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
