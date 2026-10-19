"""Compile model-designed local dodge/burn into native luminosity curves.

ChatGPT supplies the observed lighting, purpose and reviewed region. This module
does not recognize light or subjects. Strength is relative, not physical EV.
"""
from __future__ import annotations
import math


def light_curve(action: str, strength: float) -> list[list[float]]:
    if action not in {'dodge', 'burn'}:
        raise ValueError('Local light action must be dodge or burn')
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or not 0 <= strength <= 100:
        raise ValueError('Local light strength must be finite and within 0..100')
    k = 2 * strength / 100
    points = []
    for value in list(range(0, 256, 32)) + [255]:
        t = value / 255
        # Monotonic curves preserve brightness ordering and black/white endpoints.
        y = 1 - (1 - t) * math.exp(-k * t) if action == 'dodge' else t * math.exp(-k * (1 - t))
        points.append([value, round(y * 255, 4)])
    points[0][1], points[-1][1] = 0, 255
    return points


def compile_local_light(step: dict) -> tuple[dict, dict]:
    if step.get('blend', 'luminosity') != 'luminosity' or step.get('channels'):
        raise ValueError('Local light uses generated luminosity curves; use curves for custom color changes')
    region = step.get('region', {})
    if region.get('kind') != 'annotation' or not region.get('id'):
        raise ValueError('Local light requires a reviewed ChatGPT annotation region')
    if not isinstance(step.get('purpose'), str) or not step['purpose'].strip():
        raise ValueError('Local light requires a photo-specific purpose')
    points = light_curve(step.get('action'), step.get('strength'))
    compiled = {'kind': 'curves', 'name': step.get('name'),
                'channels': {'composite': points}, 'blend': 'luminosity',
                'opacity': step.get('opacity', 100), 'region': dict(region)}
    proof = {'name': step.get('name'), 'action': step['action'], 'strength': step['strength'],
             'opacity': step.get('opacity', 100), 'purpose': step['purpose'],
             'annotation_id': region['id'], 'invert': bool(region.get('invert', False)),
             'blend': 'luminosity', 'native_curve_points': points,
             'strength_unit': 'relative curve control; not physical EV'}
    return compiled, proof
