"""Copy a CR2's camera-embedded JPEG for inspection/reference, never for final pixels."""
import argparse
import hashlib
import io
import json
import struct
from pathlib import Path
import tifffile
from PIL import Image


def main():
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    source = args.source.resolve(strict=True)
    if source.suffix.lower() != '.cr2' or '.downloading' in source.name:
        raise ValueError('Completed CR2 required')
    if args.output.exists() or args.output.resolve() == source:
        raise FileExistsError('Use a fresh output path')
    data = source.read_bytes()
    with tifffile.TiffFile(source) as tf:
        page = tf.pages[0]
        if tuple(page.shape[-1:]) != (3,) or int(page.tags['Compression'].value) != 6:
            raise ValueError('IFD0 is not the expected camera JPEG preview')
        offsets = page.dataoffsets
        sizes = page.databytecounts
        if len(offsets) != 1:
            raise ValueError('Unsupported fragmented preview')
        preview = data[offsets[0]:offsets[0]+sizes[0]]
        orientation = int(page.tags[274].value) if 274 in page.tags else 1
    if not preview.startswith(b'\xff\xd8') or not preview.endswith(b'\xff\xd9'):
        raise ValueError('Embedded JPEG is incomplete')
    with Image.open(io.BytesIO(preview)) as image:
        existing_exif = image.getexif()
    if existing_exif and existing_exif.get(274, 1) != orientation:
        raise ValueError('Embedded EXIF disagrees with CR2 orientation; use Photoshop baseline')
    if not existing_exif and orientation != 1:
        exif = Image.Exif()
        exif[274] = orientation
        metadata = exif.tobytes()
        # Insert orientation metadata; compressed pixel bytes are not re-encoded.
        preview = preview[:2] + b'\xff\xe1' + struct.pack('>H', len(metadata)+2) + metadata + preview[2:]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(preview)
    record = {'source': str(source), 'source_sha256': hashlib.sha256(data).hexdigest(),
              'preview': str(args.output.resolve()), 'pixel_origin': 'camera-embedded JPEG', 'orientation': orientation,
              'purpose': 'inspection and image2 reference only; final must be developed from source RAW'}
    args.output.with_suffix('.provenance.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False))


if __name__ == '__main__':
    main()
