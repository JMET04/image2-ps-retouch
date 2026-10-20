"""Compile visually reviewed, small same-photo clone patches. No synthesis."""
import math


def compile_patch(step, compiled):
    if not compiled or step.get('category') not in {'dust','temporary_blemish'}:
        raise ValueError('Patch needs reviewed model geometry and an explicit blemish category')
    if not isinstance(step.get('purpose'),str) or not step['purpose'].strip():
        raise ValueError('Patch needs the observed defect and donor suitability')
    if set(step)-{'kind','name','category','purpose','target_id','donor_id','opacity'}:
        raise ValueError('Patch geometry must come from its reviewed annotation artifact')
    if not isinstance(step.get('opacity',100),(int,float)) or not 0<step.get('opacity',100)<=100:
        raise ValueError('Invalid patch opacity')
    w,h=compiled['canvas']
    def region(key):
        r=compiled['regions'].get(step.get(key))
        if not r or len(r['contours'])!=1 or r['contours'][0]['operation']!='add':
            raise ValueError('Patch donor and target each need one reviewed positive contour')
        return r,[[p[0]*w,p[1]*h] for p in r['contours'][0]['points']]
    target,tp=region('target_id');donor,dp=region('donor_id')
    if len(tp)!=len(dp):raise ValueError('Donor must have the same shape and size as target')
    dx,dy=dp[0][0]-tp[0][0],dp[0][1]-tp[0][1]
    if any(abs(b[0]-a[0]-dx)>.01 or abs(b[1]-a[1]-dy)>.01 for a,b in zip(tp,dp)):
        raise ValueError('Donor geometry must be an untranslated-size copy of target')
    xs,ys=[p[0] for p in tp],[p[1] for p in tp]
    bounds=[min(xs),min(ys),max(xs),max(ys)]
    bw,bh=bounds[2]-bounds[0],bounds[3]-bounds[1]
    limit=128 if step['category']=='dust' else 48
    feather=target['feather_px']
    if not (2<=bw<=limit and 2<=bh<=limit and 0<feather<=min(bw,bh)/2):
        raise ValueError('Patch is too large or lacks controlled native feathering')
    if bw*bh>w*h*.0005:raise ValueError('Patch covers too much of the photograph')
    if math.hypot(dx,dy)<=max(bw,bh)+6*feather:
        raise ValueError('Donor overlaps the defect or its feather support')
    # Photoshop selection feather has support beyond the contour. Copy enough
    # real donor pixels that the soft mask never reveals a hard pasted edge.
    pad=math.ceil(3*feather)+2
    donor_bounds=[math.floor(bounds[0]+dx)-pad,math.floor(bounds[1]+dy)-pad,
                  math.ceil(bounds[2]+dx)+pad,math.ceil(bounds[3]+dy)+pad]
    target_bounds=[donor_bounds[0]-dx,donor_bounds[1]-dy,donor_bounds[2]-dx,donor_bounds[3]-dy]
    for b in [donor_bounds,target_bounds]:
        if not (0<=b[0]<b[2]<=w and 0<=b[1]<b[3]<=h):
            raise ValueError('Patch or feather support crosses the canvas edge')
    native={'kind':'clone_patch','name':step['name'],'opacity':step.get('opacity',100),
            'donor_bounds':donor_bounds,'target_bounds':target_bounds,'region':target}
    proof={'name':step['name'],'category':step['category'],'purpose':step['purpose'],
           'target_id':step['target_id'],'donor_id':step['donor_id'],
           'donor_bounds':donor_bounds,'target_bounds':target_bounds,'feather_px':feather,
           'pixel_source':'same document visible original-photo composite before new light adjustments',
           'method':'native small clone patch on independent masked pixel layer; no healing synthesis'}
    return native,proof
