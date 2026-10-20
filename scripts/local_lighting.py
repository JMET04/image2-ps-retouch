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
    response=step.get('response','relative')
    if response == 'exposure':
        stops=step.get('stops')
        if (type(stops) not in (int,float) or not math.isfinite(stops) or not 0<stops<=1
                or step.get('strength') is not None or tonal_focus!='all' or white_ceiling!=255
                or step.get('action') not in {'dodge','burn'}):
            raise ValueError('Exposure response uses 0..1 stops, no strength, all tones and protected white endpoint')
        factor=2**(stops if step['action']=='dodge' else -stops)
        points=[]
        # Photoshop Curves admits at most 14 control points. Nine points also
        # retain the proven native recipe format used by relative responses.
        for value in list(range(0,256,32))+[255]:
            t=value/255
            linear=t/12.92 if t<=.04045 else ((t+.055)/1.055)**2.4
            lit=factor*linear/(1+(factor-1)*linear)
            y=12.92*lit if lit<=.0031308 else 1.055*lit**(1/2.4)-.055
            points.append([value,round(y*255,4)])
        points[0][1]=0;points[-1][1]=255
    elif response == 'relative':
        points = light_curve(step.get('action'), step.get('strength'), tonal_focus, white_ceiling)
    else:raise ValueError('Unknown local light response')
    compiled = {'kind': 'curves', 'name': step.get('name'),
                'channels': {'composite': points}, 'blend': 'luminosity',
                'opacity': step.get('opacity', 100), 'region': dict(region)}
    proof = {'name': step.get('name'), 'action': step['action'], 'strength': step.get('strength'),
             'opacity': step.get('opacity', 100), 'purpose': step['purpose'],
             'annotation_id': region['id'], 'invert': bool(region.get('invert', False)),
             'blend': 'luminosity', 'native_curve_points': points,
             'tonal_focus': tonal_focus,
             'white_ceiling': white_ceiling,
             'response':response,'stops':step.get('stops'),
             'strength_unit': ('display-referred sRGB gray exposure response with highlight shoulder; not physical relighting' if response=='exposure' else 'relative curve control; not physical EV')}
    return compiled, proof
