"""Compare reviewed corresponding regions and fit PS curve PARAMETERS only.

No semantic recognition, image generation, final retouch pixels, or PS auto
selection. Region positions and correspondence decisions are model-provided.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageFilter, ImageOps
from scipy.optimize import minimize
from skimage.color import deltaE_ciede2000, rgb2lab


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def display_rgb(path, target_size=None, generated=False):
    """Read an existing display file with its actual source color meaning."""
    with Image.open(path) as source:
        source.load()
        icc = source.info.get('icc_profile')
        exif_srgb = source.getexif().get_ifd(0x8769).get(40961) == 1
        im = ImageOps.exif_transpose(source).convert('RGB')
        if icc:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            if 'srgb' not in ImageCms.getProfileDescription(profile).lower():
                converted = ImageCms.profileToProfile(im, profile, ImageCms.createProfile('sRGB'), outputMode='RGB')
                im.close()
                im = converted
        elif not generated and not exif_srgb:
            im.close()
            raise ValueError('Untagged original/output has no verified sRGB meaning')
        if target_size:
            resized = im.resize(target_size, Image.Resampling.LANCZOS)
            im.close()
            im = resized
        return im


def region_mask(size, region):
    """Rasterize declared model marks; never infer a subject or sky."""
    if not region.get('model_reviewed') or not region.get('correspondence_notes'):
        raise ValueError('Comparison regions require actual model-reviewed correspondence')
    im = Image.new('L', size, 0)
    d = ImageDraw.Draw(im)
    kind = region.get('kind')
    if kind == 'rectangle':
        b = region['bounds']
        if len(b) != 4 or not all(0 <= n <= 1 for n in b) or b[0] >= b[2] or b[1] >= b[3]:
            raise ValueError('Invalid normalized sampling bounds')
        d.rectangle(tuple(round(v * size[i % 2]) for i, v in enumerate(b)), fill=255)
    elif kind == 'polygon':
        points = region['points']
        if len(points) < 3 or any(len(p) != 2 or any(not 0 <= v <= 1 for v in p) for p in points):
            raise ValueError('Invalid reviewed sampling polygon')
        d.polygon([(round(x * size[0]), round(y * size[1])) for x, y in points], fill=255)
    else:
        raise ValueError('No automatic region discovery supported')
    result = np.asarray(im) > 0
    im.close()
    if result.sum() < 16:
        raise ValueError('Sampling area is too small')
    return result


def low_frequency_pair(current, reference, width=512):
    with Image.open(current) as src:
        upright = ImageOps.exif_transpose(src)
        h = round(width * upright.height / upright.width)
    size = (width, h)
    a = display_rgb(current, size)
    b = display_rgb(reference, size, generated=True)
    # Low frequency is for tone/color matching, not an excuse to ignore edges.
    blur = max(1.5, width / 160)
    aa = a.filter(ImageFilter.GaussianBlur(blur))
    bb = b.filter(ImageFilter.GaussianBlur(blur))
    arr_a = np.asarray(aa).astype(np.float64) / 255
    arr_b = np.asarray(bb).astype(np.float64) / 255
    for im in (a, b, aa, bb):
        im.close()
    return arr_a, arr_b, size


def region_metrics(current, reference, regions, *, correspondence_reviewed=False):
    if not correspondence_reviewed:
        raise ValueError('Cannot score without a reviewed same-frame correspondence')
    a, b, size = low_frequency_pair(current, reference)
    la, lb = rgb2lab(a), rgb2lab(b)
    color = deltaE_ciede2000(la, lb)
    results = []
    for region in regions:
        mask = region_mask(size, region)
        # Median absolute pixel delta and median-value delta are both needed:
        # equal medians alone can conceal incompatible illumination patterns.
        l_current = float(np.median(la[:, :, 0][mask]))
        l_ref = float(np.median(lb[:, :, 0][mask]))
        results.append({
            'id': region['id'], 'role': region.get('role', 'environment'),
            'samples': int(mask.sum()), 'L_current_median': round(l_current, 3),
            'L_reference_median': round(l_ref, 3),
            'L_median_difference': round(l_current - l_ref, 3),
            'L_absolute_pixel_difference_median': round(float(np.median(np.abs(la[:, :, 0] - lb[:, :, 0])[mask])), 3),
            'deltaE00_median': round(float(np.median(color[mask])), 3),
            'deltaE00_p90': round(float(np.percentile(color[mask], 90)), 3),
        })
    return {'current': str(current), 'current_sha256': sha(current),
            'reference': str(reference), 'reference_sha256': sha(reference),
            'comparison_size': list(size), 'low_frequency_sigma_px': max(1.5, size[0] / 160),
            'regions': results, 'visual_acceptance': 'pending',
            'scope': 'Reviewed corresponding low-frequency regions; no automatic artistic acceptance or texture reconstruction'}


CURVE_KNOTS = np.array([0, 24, 48, 80, 112, 144, 184, 224, 255.], dtype=float)


def curve_coverage(x):
    x=np.asarray(x,dtype=float).ravel()
    if len(x)<16 or not np.all(np.isfinite(x)):
        raise ValueError('Coverage requires at least 16 finite samples')
    boundaries=(CURVE_KNOTS[:-1]+CURVE_KNOTS[1:])/2
    counts=np.bincount(np.searchsorted(boundaries,x),minlength=len(CURVE_KNOTS))
    supported=counts>=max(8,len(x)*.01)
    return dict(sample_count=len(x),sample_range=[float(x.min()),float(x.max())],
                percentile_10_90=[float(v) for v in np.percentile(x,[10,90])],
                knot_sample_counts=counts.tolist(),
                unsupported_knots=CURVE_KNOTS[~supported].tolist(),
                scope='Sampling coverage only; unobserved tonal ranges require protection and native review')


def fit_channel(x, y, *, uncovered_identity_weight=0.0):
    """Robust, monotonic nine-knot sRGB curve, endpoints fixed."""
    knots = CURVE_KNOTS
    x,y=np.asarray(x,dtype=float).ravel(),np.asarray(y,dtype=float).ravel()
    if x.shape!=y.shape or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError('Curve samples must have matching shapes and finite values')
    if not np.isfinite(uncovered_identity_weight) or uncovered_identity_weight<0:
        raise ValueError('Unsupported-tone protection weight must be finite and nonnegative')
    if len(x) > 40000:
        take = np.linspace(0, len(x) - 1, 40000, dtype=int)
        x, y = x[take], y[take]
    inside = (x > 2) & (x < 253)
    x, y = x[inside], y[inside]
    if len(x) < 16:
        raise ValueError('Insufficient midtone samples')
    coverage=curve_coverage(x)
    unsupported=np.isin(knots,coverage['unsupported_knots'])
    # Huber loss limits high-frequency redraw and mismatched tiny edges.
    def objective(v):
        output = np.r_[0, v, 255]
        residual = np.interp(x, knots, output) - y
        abs_r = np.abs(residual)
        huber = np.where(abs_r <= 10, residual * residual / 2, 10 * (abs_r - 5))
        regularization = .003 * np.mean((output - knots) ** 2) + .02 * np.mean(np.diff(output - knots, 2) ** 2)
        if uncovered_identity_weight and np.any(unsupported):
            regularization += uncovered_identity_weight * np.mean((output[unsupported]-knots[unsupported])**2)
        return float(np.mean(huber) + regularization)
    constraint = {'type': 'ineq', 'fun': lambda v: np.diff(np.r_[0, v, 255]) - .01}
    fit = minimize(objective, knots[1:-1], method='SLSQP', bounds=[(0, 255)] * 7,
                   constraints=[constraint], options={'maxiter': 200, 'ftol': 1e-7})
    if not fit.success:
        raise ValueError('Curve fitting failed: ' + fit.message)
    values = np.r_[0, fit.x, 255]
    values = np.maximum.accumulate(np.round(values, 3))
    return [[float(k), float(v)] for k, v in zip(knots, values)]


def fit_rgb_curves(current, reference, region=None, *, correspondence_reviewed=False):
    if not correspondence_reviewed:
        raise ValueError('Fitting requires actual reviewed correspondence')
    a, b, size = low_frequency_pair(current, reference)
    mask = region_mask(size, region) if region else np.ones((size[1], size[0]), dtype=bool)
    return {name: fit_channel(a[:, :, i][mask].ravel() * 255, b[:, :, i][mask].ravel() * 255)
            for i, name in enumerate(('red', 'green', 'blue'))}


def fit_rgb_curves_report(current, reference, sampling_regions, *, correspondence_reviewed=False,
                          uncovered_identity_weight=.3):
    """Balance reviewed material/light-plane samples and expose extrapolation.

    Returns editable curve parameters and evidence only. The caller still
    chooses the application mask and inspects the actual Photoshop result.
    """
    if not correspondence_reviewed or not sampling_regions:
        raise ValueError('Explicit reviewed corresponding material regions are required')
    a,b,size=low_frequency_pair(current,reference)
    samples=[];regions=[]
    counts=[]
    for region in sampling_regions:
        indices=np.flatnonzero(region_mask(size,region).ravel())
        if len(indices)<16:raise ValueError('Too few material samples: '+region['id'])
        samples.append(indices);counts.append(len(indices))
    per_region=min(4000,min(counts))
    for region,indices in zip(sampling_regions,samples):
        regions.append(dict(id=region['id'],available_samples=len(indices),used_samples=per_region))
    take=np.concatenate([indices[np.linspace(0,len(indices)-1,per_region,dtype=int)] for indices in samples])
    x=a.reshape(-1,3)[take]*255;y=b.reshape(-1,3)[take]*255
    curves={};coverage={}
    for i,name in enumerate(('red','green','blue')):
        curves[name]=fit_channel(x[:,i],y[:,i],uncovered_identity_weight=uncovered_identity_weight)
        coverage[name]=curve_coverage(x[:,i])
    return dict(curves=curves,coverage=coverage,sampling_regions=regions,
        current=str(current),current_sha256=sha(current),reference=str(reference),reference_sha256=sha(reference),
        uncovered_identity_weight=uncovered_identity_weight,visual_acceptance='pending',
        scope='Balanced low-frequency curve parameters; native output and 100% edges still require review')
