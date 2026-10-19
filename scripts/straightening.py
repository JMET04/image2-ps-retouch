"""Geometry only: level a reviewed model-marked line, never detect a horizon."""
import math


def compile_straightening(spec, compiled):
    if not isinstance(spec, dict) or not compiled:
        raise ValueError('Straightening requires reviewed source-bound annotations')
    if set(spec) - {'region_id', 'crop_size', 'center_offset', 'reason'}:
        raise ValueError('Straightening accepts a reviewed guide, not a supplied angle')
    if not isinstance(spec.get('reason'), str) or not spec['reason'].strip():
        raise ValueError('Record why this visible line should be level')
    region = compiled['regions'].get(spec.get('region_id'))
    if not region or len(region['contours']) != 1:
        raise ValueError('One reviewed guide contour is required')
    contour = region['contours'][0]
    if contour['operation'] != 'add' or len(contour['points']) != 4 or region['feather_px'] != 0:
        raise ValueError('Use a four-point unfeathered guide band; its first two points mark the line')
    w, h = compiled['canvas']
    a, b = [[p[0] * w, p[1] * h] for p in contour['points'][:2]]
    if b[0] - a[0] < w * .5:
        raise ValueError('The reviewed left-to-right guide must span at least half the canvas')
    angle = -math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    if not .01 <= abs(angle) <= 5:
        raise ValueError('Straightening is limited to a small .01..5 degree correction')
    size = spec.get('crop_size')
    if not isinstance(size, list) or len(size) != 2 or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in size):
        raise ValueError('Crop size must contain two native integer dimensions')
    cw, ch = size
    if cw > w or ch > h or not .7 <= cw * ch / (w * h) <= 1:
        raise ValueError('Keep at least 70% native area without enlarging either dimension')
    offset = spec.get('center_offset', [0, 0])
    if not isinstance(offset, list) or len(offset) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in offset):
        raise ValueError('Native crop center offset must be finite')
    co, si = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    for x in (-cw / 2, cw / 2):
        for y in (-ch / 2, ch / 2):
            dx, dy = x + offset[0], y + offset[1]
            ox, oy = co * dx + si * dy, -si * dx + co * dy
            if abs(ox) > w / 2 - 2 or abs(oy) > h / 2 - 2:
                raise ValueError('Crop crosses rotated source pixels; no fill or generated corners are allowed')
    return {'clockwise_degrees': angle, 'native_canvas': [w, h], 'crop_size': list(size),
            'center_offset': list(offset), 'guide_native': [a, b], 'annotation_id': spec['region_id'],
            'annotation_digest': compiled['annotation_digest'], 'reason': spec['reason'],
            'engine': 'Photoshop single canvas rotation after masks, embedded original smart object, native crop',
            'rotation_interpolation': 'one native Photoshop rotation; no resizeImage or generated fill',
            'retained_native_area': cw * ch / (w * h)}
