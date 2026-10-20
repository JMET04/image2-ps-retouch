"""Compile model-designed local dodge/burn into native luminosity curves.

ChatGPT supplies the observed lighting, purpose and reviewed region. This module
does not recognize light or subjects. Strength is relative, not physical EV.
"""
from __future__ import annotations
import math


def light_curve(action: str, strength: float, tonal_focus: str = 'all', white_ceiling: float = 255) -> list[list[float]]:
    if action not in {'dodge', 'burn'}:
        raise ValueError('Local light action must be dodge or burn')
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or not 0 <= strength <= 100:
        raise ValueError('Local light strength must be finite and within 0..100')
    if tonal_focus not in ('all', 'shadows', 'midtones', 'highlights'):
        raise ValueError('Local light tonal_focus must be all, shadows, midtones or highlights')
    if (isinstance(white_ceiling, bool) or not isinstance(white_ceiling, (int, float))
            or not math.isfinite(white_ceiling) or not 200 <= white_ceiling <= 255):
        raise ValueError('Local light white_ceiling must be finite and within 200..255')
    if action != 'burn' and white_ceiling != 255:
        raise ValueError('Only burn can lower the local white ceiling')
    k = 2 * strength / 100
    points = []
    for value in list(range(0, 256, 32)) + [255]:
        t = value / 255
        # Default curves keep both endpoints. An explicit burn ceiling quiets
        # near-white competition independently of the midtone strength.
        if tonal_focus == 'all':
            # Keep the original default exactly, including historical recipes.
            y = 1 - (1 - t) * math.exp(-k * t) if action == 'dodge' else t * math.exp(-k * (1 - t))
        else:
            amount = strength / 100
            if tonal_focus == 'midtones':
                delta = 4 * amount * t * t * (1 - t) ** 2
            else:
                coefficient = 3 * amount
                # The opposite direction needs a gentler endpoint slope to
                # remain monotonic at every strength, without clipping.
                if (tonal_focus == 'highlights' and action == 'dodge') or (tonal_focus == 'shadows' and action == 'burn'):
                    coefficient /= 1 + coefficient
                weight = t ** 3 * (1 - t) if tonal_focus == 'highlights' else t * (1 - t) ** 3
                delta = coefficient * weight
            y = t + delta if action == 'dodge' else t - delta
        points.append([value, round(y * 255 - (255 - white_ceiling) * t ** 3, 4)])
    points[0][1], points[-1][1] = 0, white_ceiling
    return points


def compile_local_light(step: dict) -> tuple[dict, dict]:
    if step.get('blend', 'luminosity') != 'luminosity' or step.get('channels'):
        raise ValueError('Local light uses generated luminosity curves; use curves for custom color changes')
    region = step.get('region', {})
    if region.get('kind') != 'annotation' or not region.get('id'):
        raise ValueError('Local light requires a reviewed ChatGPT annotation region')
    if not isinstance(step.get('purpose'), str) or not step['purpose'].strip():
        raise ValueError('Local light requires a photo-specific purpose')
    tonal_focus = step.get('tonal_focus', 'all')
    white_ceiling = step.get('white_ceiling', 255)
    points = light_curve(step.get('action'), step.get('strength'), tonal_focus, white_ceiling)
    compiled = {'kind': 'curves', 'name': step.get('name'),
                'channels': {'composite': points}, 'blend': 'luminosity',
                'opacity': step.get('opacity', 100), 'region': dict(region)}
    proof = {'name': step.get('name'), 'action': step['action'], 'strength': step['strength'],
             'opacity': step.get('opacity', 100), 'purpose': step['purpose'],
             'annotation_id': region['id'], 'invert': bool(region.get('invert', False)),
             'blend': 'luminosity', 'native_curve_points': points,
             'tonal_focus': tonal_focus,
             'white_ceiling': white_ceiling,
             'strength_unit': 'relative curve control; not physical EV'}
    return compiled, proof
