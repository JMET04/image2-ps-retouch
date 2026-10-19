"""Map ChatGPT's visually reviewed marks to the native Photoshop canvas.

This module does not recognize objects. Recognition and edge decisions belong to
the model viewing the actual baseline and detail crops. It only validates,
transforms, previews and records that work; previews never become photo pixels.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

RAW = {'.cr2', '.cr3', '.nef', '.arw', '.dng'}
TOLERANCE = .5  # maximum flattening error, measured on the native canvas


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_fresh(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)


def image_size(path):
    with Image.open(path) as im:
        return list(ImageOps.exif_transpose(im).size)


def digest(data):
    # Review cannot remain valid after moving a contour, changing feather or
    # replacing the image/crop against which the contour was drawn.
    body = {k: data[k] for k in ('schema_version', 'source', 'baseline', 'canvas', 'views', 'regions')}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True,
                                     separators=(',', ':')).encode()).hexdigest()


def initialize(source, baseline, prepared_report=None):
    source, baseline = Path(source).resolve(strict=True), Path(baseline).resolve(strict=True)
    source_hash = sha(source)
    if source.suffix.lower() in RAW:
        if prepared_report is None:
            raise ValueError('RAW annotations require the successful Photoshop prepare report')
        proof = read_json(prepared_report)
        recipe = read_json(proof['recipe'])
        if not (proof.get('original_unchanged') is True and proof.get('source_sha256') == source_hash
                and recipe.get('stage') == 'prepare'
                and Path(recipe['source']).resolve() == source
                and Path(recipe['output_base'] + '_baseline.jpg').resolve() == baseline):
            raise ValueError('Prepare report does not bind this RAW to this baseline')
    width, height = image_size(baseline)
    return {
        'schema_version': 1,
        'source': {'path': str(source), 'sha256': source_hash},
        'baseline': {'path': str(baseline), 'sha256': sha(baseline),
                     'prepared_report': str(Path(prepared_report).resolve()) if prepared_report else None},
        'canvas': {'width': width, 'height': height, 'orientation': 'native_upright'},
        'views': [{'id': 'baseline', 'path': str(baseline), 'sha256': sha(baseline),
                   'native_bounds': [0, 0, width, height], 'size': [width, height]}],
        'regions': [],
        'review': {'status': 'pending', 'method': 'chatgpt_vision', 'notes': ''},
    }


def number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Invalid {label}')
    return value


def pair(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('A coordinate must be [x,y] in its declared view')
    return [number(v, 0, 1, 'normalized coordinate') for v in value]


def point_to_native(point, view):
    x, y = pair(point)
    left, top, right, bottom = view['native_bounds']
    return [left + x * (right - left), top + y * (bottom - top)]


def midpoint(a, b):
    return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]


def segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = dx * dx + dy * dy
    if not d:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / d))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def flatten_cubic(p0, p1, p2, p3, depth=0):
    if max(segment_distance(p1, p0, p3), segment_distance(p2, p0, p3)) <= TOLERANCE:
        return [p3]
    if depth >= 20:
        raise ValueError('Curve cannot be flattened within the native pixel tolerance')
    a, b, c = midpoint(p0, p1), midpoint(p1, p2), midpoint(p2, p3)
    d, e = midpoint(a, b), midpoint(b, c)
    f = midpoint(d, e)
    return flatten_cubic(p0, a, d, f, depth + 1) + flatten_cubic(f, e, c, p3, depth + 1)


def contour_points(contour, view):
    kind = contour.get('kind')
    if kind == 'polygon':
        points = [point_to_native(p, view) for p in contour.get('points', [])]
    elif kind == 'bezier':
        nodes = contour.get('nodes', [])
        if len(nodes) < 3:
            raise ValueError('A closed Bezier contour requires at least three nodes')
        anchors = [point_to_native(n['anchor'], view) for n in nodes]
        points = [anchors[0]]
        for i, node in enumerate(nodes):
            following = (i + 1) % len(nodes)
            points.extend(flatten_cubic(anchors[i], point_to_native(node.get('out', node['anchor']), view),
                                       point_to_native(nodes[following].get('in', nodes[following]['anchor']), view),
                                       anchors[following]))
        points.pop()  # selection closes the final segment itself
    elif kind == 'ellipse':
        b = contour.get('bounds', [])
        if len(b) != 4 or not (b[0] < b[2] and b[1] < b[3]):
            raise ValueError('Ellipse bounds must have positive width and height')
        a, z = point_to_native(b[:2], view), point_to_native(b[2:], view)
        cx, cy, rx, ry = (a[0] + z[0]) / 2, (a[1] + z[1]) / 2, (z[0] - a[0]) / 2, (z[1] - a[1]) / 2
        radius = max(rx, ry)
        count = max(16, math.ceil(math.pi / math.acos(max(-1, 1 - min(TOLERANCE / radius, 1)))))
        points = [[cx + rx * math.cos(2 * math.pi * i / count),
                   cy + ry * math.sin(2 * math.pi * i / count)] for i in range(count)]
    else:
        raise ValueError('Only model-marked polygon, bezier or ellipse contours are supported')
    if len(points) < 3 or len(points) > 12000:
        raise ValueError('Contour requires 3..12000 vertices')
    area = abs(sum(points[i][0] * points[(i + 1) % len(points)][1]
                   - points[(i + 1) % len(points)][0] * points[i][1] for i in range(len(points)))) / 2
    if area < .25:
        raise ValueError('Contour encloses no useful native area')
    return points


def compile_annotations(data, require_review=True, expected_source=None):
    if data.get('schema_version') != 1 or data.get('canvas', {}).get('orientation') != 'native_upright':
        raise ValueError('Unknown annotation schema or orientation')
    width, height = data['canvas']['width'], data['canvas']['height']
    if not all(isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 100000 for v in (width, height)):
        raise ValueError('Invalid native canvas dimensions')
    for key in ('source', 'baseline'):
        path = Path(data[key]['path']).resolve(strict=True)
        if sha(path) != data[key]['sha256']:
            raise ValueError(f'{key} changed after annotation')
    if expected_source and Path(expected_source).resolve() != Path(data['source']['path']).resolve():
        raise ValueError('Annotations belong to a different source photo')
    if image_size(data['baseline']['path']) != [width, height]:
        raise ValueError('Baseline dimensions do not match the native canvas')
    views = {}
    for view in data['views']:
        if not view.get('id') or view['id'] in views:
            raise ValueError('View IDs must be unique')
        b = view['native_bounds']
        if len(b) != 4 or not all(isinstance(v, int) and not isinstance(v, bool) for v in b):
            raise ValueError('Detail crops require exact native integer bounds')
        if not (0 <= b[0] < b[2] <= width and 0 <= b[1] < b[3] <= height):
            raise ValueError('View falls outside the native canvas')
        if sha(view['path']) != view['sha256'] or image_size(view['path']) != view['size']:
            raise ValueError('Annotation view changed')
        if view['size'] != [b[2] - b[0], b[3] - b[1]]:
            raise ValueError('Use an unresampled native view; do not map a thumbnail as a detail crop')
        # A crop must really show the declared location, not merely have the same size.
        if not (Path(view['path']).resolve() == Path(data['baseline']['path']).resolve()
                and b == [0, 0, width, height]):
            with Image.open(data['baseline']['path']) as original, Image.open(view['path']) as crop:
                upright = ImageOps.exif_transpose(original)
                target = upright.crop(b).convert('RGB')
                actual = ImageOps.exif_transpose(crop).convert('RGB')
                if target.tobytes() != actual.tobytes():
                    raise ValueError('View pixels do not match their declared baseline bounds')
                upright.close()
                target.close()
                actual.close()
        views[view['id']] = view
    regions = {}
    for region in data['regions']:
        region_id = region.get('id')
        if not isinstance(region_id, str) or not region_id or region_id in regions:
            raise ValueError('Region IDs must be unique nonempty strings')
        if not all(isinstance(region.get(k), str) and region[k].strip() for k in ('label', 'intent', 'edge_notes')):
            raise ValueError('Each region requires its visible label, intent and edge uncertainty notes')
        if region.get('confidence') not in {'high', 'medium', 'low'}:
            raise ValueError('Record model uncertainty for every region')
        feather = number(region.get('feather_px', 0), 0, min(250, min(width, height) * .2), 'native feather')
        feather_mode = region.get('feather_mode', 'combined')
        if feather_mode not in {'combined', 'per_contour'}:
            raise ValueError('Unknown feather mode')
        if feather_mode == 'per_contour' and feather != 0:
            raise ValueError('Per-contour feather requires final feather_px=0; do not blur subject protection again')
        contours = []
        for contour in region.get('contours', []):
            if contour.get('view_id') not in views:
                raise ValueError('Contour refers to an unknown image view')
            operation = contour.get('operation', 'add')
            if operation not in {'add', 'subtract'}:
                raise ValueError('Contour operation must be add or subtract')
            points = contour_points(contour, views[contour['view_id']])
            compiled_contour = {'operation': operation, 'points': [[x / width, y / height] for x, y in points]}
            if feather_mode == 'per_contour':
                compiled_contour['feather_px'] = number(contour.get('feather_px'), 0,
                    min(250, min(width, height) * .2), 'per-contour native feather')
            elif 'feather_px' in contour:
                raise ValueError('Contour feather requires explicit per_contour mode')
            contours.append(compiled_contour)
        if not contours or not any(c['operation'] == 'add' for c in contours):
            raise ValueError('A region needs at least one positive contour')
        regions[region_id] = {'kind': 'annotated', 'id': region_id, 'label': region['label'],
                              'contours': contours, 'feather_px': feather}
        if feather_mode == 'per_contour':
            regions[region_id]['feather_mode'] = feather_mode
    if not regions:
        raise ValueError('No model annotations: an empty draft is not object recognition')
    current_digest = digest(data)
    if require_review:
        review = data.get('review', {})
        if not (review.get('status') == 'accepted' and review.get('method') == 'chatgpt_vision'
                and review.get('annotation_digest') == current_digest and review.get('notes', '').strip()):
            raise ValueError('View the current annotation overlay and accept its geometry before Photoshop execution')
        if sha(review['overlay_path']) != review['overlay_sha256']:
            raise ValueError('Reviewed overlay changed')
    return {'canvas': [width, height], 'annotation_digest': current_digest,
            'source_sha256': data['source']['sha256'], 'regions': regions,
            'curve_flattening_tolerance_native_px': TOLERANCE}


def overlay(data, output):
    compiled = compile_annotations(data, require_review=False)
    output = Path(output)
    report = output.with_suffix('.annotation-review.json')
    if output.exists() or report.exists():
        raise FileExistsError('Use a fresh annotation preview path')
    with Image.open(data['baseline']['path']) as im:
        image = ImageOps.exif_transpose(im).convert('RGB')
    image.thumbnail((1600, 1600))
    width, height = image.size
    colors = [(255,190,30),(50,220,245),(240,90,180),(140,235,110),(175,145,255)]
    draw = ImageDraw.Draw(image)
    legends = []
    for i, (region_id, region) in enumerate(compiled['regions'].items()):
        color = colors[i % len(colors)]
        for contour in region['contours']:
            pts = [(x * width, y * height) for x, y in contour['points']]
            draw.line(pts + [pts[0]], fill=color, width=3)
            x, y = pts[0]
            draw.rectangle((x, y, x + 32, y + 18), fill=color)
            draw.text((x + 3, y + 2), str(i + 1) + ('-' if contour['operation'] == 'subtract' else '+'), fill='black')
        legends.append({'number': i + 1, 'region_id': region_id, 'label': region['label'], 'feather_native_px': region['feather_px'],
                        'feather_mode': region.get('feather_mode', 'combined'),
                        'contour_feathers': [c.get('feather_px') for c in region['contours']]})
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    write_fresh(report, {'purpose': 'annotation geometry preview only; not a retouched photograph',
                         'annotation_digest': compiled['annotation_digest'],
                         'overlay_path': str(output.resolve()), 'overlay_sha256': sha(output),
                         'native_canvas': compiled['canvas'], 'preview_size': [width, height], 'legend': legends})
    return report


def accept(data, report_path, notes):
    report = read_json(report_path)
    compiled = compile_annotations(data, require_review=False)
    if compiled['annotation_digest'] != report.get('annotation_digest') or sha(report['overlay_path']) != report['overlay_sha256']:
        raise ValueError('The overlay does not review the current annotations')
    if not notes.strip():
        raise ValueError('Record the actual geometry and edge review')
    result = copy.deepcopy(data)
    result['review'] = {'status': 'accepted', 'method': 'chatgpt_vision', 'annotation_digest': compiled['annotation_digest'],
                        'overlay_path': report['overlay_path'], 'overlay_sha256': report['overlay_sha256'], 'notes': notes}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--source', required=True, type=Path)
    init.add_argument('--baseline', required=True, type=Path)
    init.add_argument('--prepared-report', type=Path)
    init.add_argument('--out', required=True, type=Path)
    for command in ('overlay', 'compile', 'accept'):
        action = sub.add_parser(command)
        action.add_argument('annotations', type=Path)
        action.add_argument('--out', required=True, type=Path)
        if command == 'accept':
            action.add_argument('--review-report', required=True, type=Path)
            action.add_argument('--notes', required=True)
    args = p.parse_args()
    if args.command == 'init':
        write_fresh(args.out, initialize(args.source, args.baseline, args.prepared_report))
    elif args.command == 'overlay':
        overlay(read_json(args.annotations), args.out)
    elif args.command == 'compile':
        write_fresh(args.out, compile_annotations(read_json(args.annotations)))
    else:
        write_fresh(args.out, accept(read_json(args.annotations), args.review_report, args.notes))
    print(json.dumps({'command': args.command, 'output': str(args.out.resolve())}, ensure_ascii=False))


if __name__ == '__main__':
    main()
