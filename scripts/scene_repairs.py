"""Compile model-reviewed scene distractions separately from tiny blemishes.

Only translation of same-photo, visible pixels is supported. No synthesis,
automatic recognition, scaling, rotation or reference-image pixel imports.
"""
import math


def compile_scene_patch(step, compiled):
    allowed = {'kind', 'name', 'target_id', 'donor_id', 'purpose', 'category',
               'protected_structure', 'donor_review', 'opacity', 'rgb_offset'}
    if set(step) - allowed or not compiled:
        raise ValueError('Scene repair requires reviewed source-bound annotations')
    if step.get('category') not in {'glass_reflection', 'edge_distraction'}:
        raise ValueError('Scene repair needs an explicit observed distraction category')
    for key in ('purpose', 'protected_structure', 'donor_review'):
        if not isinstance(step.get(key), str) or not step[key].strip():
            raise ValueError('Scene repair needs defect, protected structure and donor review')
    opacity = step.get('opacity', 100)
    if isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not 0 < opacity <= 100:
        raise ValueError('Invalid scene repair opacity')
    offset = step.get('rgb_offset', [0, 0, 0])
    if not isinstance(offset, list) or len(offset) != 3 or any(type(v) is not int or abs(v)>32 for v in offset):
        raise ValueError('Repair tone offset must be three bounded RGB integers')
    w, h = compiled['canvas']
    target = compiled['regions'].get(step.get('target_id'))
    donor = compiled['regions'].get(step.get('donor_id'))
    if not target or not donor:
        raise ValueError('Missing reviewed scene repair geometry')
    positives = [x for x in target['contours'] if x['operation']=='add']
    donors = [x for x in donor['contours'] if x['operation']=='add']
    if len(positives)!=1 or len(donors)!=1 or len(donor['contours'])!=1:
        raise ValueError('Scene repair needs one positive target and one translated donor')
    tp, dp = positives[0]['points'], donors[0]['points']
    if len(tp)!=len(dp):
        raise ValueError('Scene donor must have the same geometry')
    dx, dy = (dp[0][0]-tp[0][0])*w, (dp[0][1]-tp[0][1])*h
    if abs(dx-round(dx))>.01 or abs(dy-round(dy))>.01:
        raise ValueError('Scene translation must use integer native pixels')
    dx, dy = round(dx), round(dy)
    if any(abs((b[0]-a[0])*w-dx)>.01 or abs((b[1]-a[1])*h-dy)>.01 for a,b in zip(tp,dp)):
        raise ValueError('Scene donor may only translate, never deform')
    xs, ys = [p[0]*w for p in tp], [p[1]*h for p in tp]
    if (max(xs)-min(xs))*(max(ys)-min(ys)) > w*h*.15:
        raise ValueError('Scene patch is too broad; redesign the restoration')
    feather = max([target['feather_px']] + [c.get('feather_px', 0) for c in target['contours']])
    if not 0 < feather <= 150 or target.get('broad_feather_px'):
        raise ValueError('Scene repair needs controlled native feather, no broad light field')
    if math.hypot(dx,dy) <= 6*feather:
        raise ValueError('Scene donor is too close to the defect')
    pad = math.ceil(3*feather)+2
    # A distraction may touch the frame. Clip support at the original canvas;
    # never reflect, expand, scale or synthesize pixels outside that canvas.
    tb = [max(0,math.floor(min(xs))-pad), max(0,math.floor(min(ys))-pad),
          min(w,math.ceil(max(xs))+pad), min(h,math.ceil(max(ys))+pad)]
    db = [tb[0]+dx,tb[1]+dy,tb[2]+dx,tb[3]+dy]
    if not (0<=db[0]<db[2]<=w and 0<=db[1]<db[3]<=h):
        raise ValueError('Donor including feather support crosses original canvas')
    native = {'kind':'scene_patch','name':step['name'],'opacity':opacity,
              'target_bounds':tb,'donor_bounds':db,'region':target,'rgb_offset':offset}
    proof = {k:step[k] for k in ('name','category','purpose','protected_structure','donor_review','target_id','donor_id')}
    proof.update(target_bounds=tb,donor_bounds=db,rgb_offset=offset,
                 pixel_source='same document original-photo pixels before new adjustments',
                 method='native translated raster layer with reviewed mask; no synthesis or scaling',
                 acceptance='pending whole-frame and native target, donor, boundary review')
    return native, proof
