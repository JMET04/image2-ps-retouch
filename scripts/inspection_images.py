"""Read-only visual inspection aids. These are never retouched deliverables."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps


def load(path):
    if '.downloading' in path.name:
        raise ValueError('Download is not complete')
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert('RGB'), im.info.get('icc_profile')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('photos', nargs='+', type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--bounds', nargs=4, type=int, help='Exact native pixel crop; requires one input')
    args = p.parse_args()
    if args.out.exists():
        raise FileExistsError('Use a new inspection path')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    records = []
    if args.bounds:
        if len(args.photos) != 1:
            raise ValueError('One photograph per native detail crop')
        im, profile = load(args.photos[0])
        x0, y0, x1, y1 = args.bounds
        if not (0 <= x0 < x1 <= im.width and 0 <= y0 < y1 <= im.height):
            raise ValueError('Crop outside oriented native image')
        im.crop(args.bounds).save(args.out, icc_profile=profile)
        records.append({'file': str(args.photos[0].resolve()), 'bounds': args.bounds,
                        'native_size': list(im.size), 'resampled': False})
    else:
        cell_w, cell_h, cols = 600, 430, 2
        sheet = Image.new('RGB', (cols*cell_w, 40+math.ceil(len(args.photos)/cols)*cell_h), '#202020')
        draw = ImageDraw.Draw(sheet)
        draw.text((12, 12), 'INSPECTION ONLY - scaled overview; focus needs native detail review', fill='white')
        for i, path in enumerate(args.photos):
            im, _ = load(path)
            size = im.size
            im.thumbnail((cell_w-20, cell_h-45))
            x, y = (i % cols)*cell_w, 40+(i // cols)*cell_h
            sheet.paste(im, (x+(cell_w-im.width)//2, y+(cell_h-35-im.height)//2))
            draw.text((x+12, y+cell_h-25), f'{path.name} | {size[0]}x{size[1]}', fill='white')
            records.append({'file': str(path.resolve()), 'native_size': list(size), 'resampled': True})
        sheet.save(args.out)
    for record in records:
        record['sha256'] = hashlib.sha256(Path(record['file']).read_bytes()).hexdigest()
    args.out.with_suffix('.inspection.json').write_text(json.dumps(
        {'purpose': 'inspection only; never a final photograph', 'inputs': records},
        ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'inspection': str(args.out.resolve()), 'photos': len(records)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
