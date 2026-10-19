"""Validate a photo recipe and run it inside an already running Photoshop."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from native_guard import NativeGuard, disk_preflight, IDLE_PROBE, atomic_json, claim_fresh_small_session
from project_session import check_session
from artifact_evidence import fingerprint
from photo_annotations import compile_annotations, read_json, sha
from local_lighting import compile_local_light
from straightening import compile_straightening


def validate(job: dict, recipe_dir: Path | None = None) -> dict:
    source = Path(job['source']).resolve(strict=True)
    if source.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.cr2', '.cr3', '.nef', '.arw', '.dng'}:
        raise ValueError('Unsupported original format')
    if '.downloading' in source.name:
        raise ValueError('Download is not complete')
    stage = job.get('stage', 'retouch')
    if stage not in {'prepare', 'retouch'}:
        raise ValueError('Unknown stage')
    if 'save_psd' in job and (not isinstance(job['save_psd'], bool) or stage != 'retouch'):
        raise ValueError('save_psd is a boolean retouch-only output option')
    if job.get('input_profile') and (job['input_profile'] not in {'sRGB IEC61966-2.1', 'Adobe RGB (1998)', 'ProPhoto RGB'} or not job.get('input_profile_evidence')):
        raise ValueError('Input profile assignment requires a supported profile and evidence')
    if job.get('working_profile') and (job['working_profile'] != 'sRGB IEC61966-2.1'
                                      or not isinstance(job.get('working_profile_reason'), str)
                                      or not job['working_profile_reason'].strip()):
        raise ValueError('Reference matching supports an explicitly justified sRGB working profile')
    if job.get('scratch_history_policy') and (job['scratch_history_policy'] != 'discard_owned_history'
                                             or stage != 'retouch'):
        raise ValueError('History cache policy applies only to an exclusive owned retouch job')
    output = Path(job['output_base']).resolve()
    if not output.name or output == source:
        raise ValueError('Output must be separate from original')
    output.parent.mkdir(parents=True, exist_ok=True)
    if stage == 'retouch':
        reference = job.get('reference', {})
        if not Path(reference.get('path', '')).is_file() or not reference.get('prompt') or not reference.get('comparison'):
            raise ValueError('Retouch requires a real reference, its prompt, and visual comparison')
        if Path(reference['path']).resolve() == source:
            raise ValueError('Reference must be distinct from original')
        if not job.get('selection', {}).get('original_review'):
            raise ValueError('Original focus/exposure/composition review is required')
        if not job.get('steps'):
            raise ValueError('Photo-specific steps are required')
    job = dict(job)
    job['steps'] = [dict(step) for step in job.get('steps', [])]
    lighting = []
    for i, step in enumerate(job['steps']):
        if step.get('kind') == 'local_light':
            plan = job.get('lighting_plan', {})
            if not isinstance(plan, dict) or any(not isinstance(plan.get(k), str) or not plan[k].strip()
                                                for k in ('observed_key_light', 'subject_priority', 'shape_intent')):
                raise ValueError('Local light requires the observed key light, subject priority and shaping intent')
            job['steps'][i], proof = compile_local_light(step)
            lighting.append(proof)
    job.pop('local_lighting_provenance', None)
    if lighting:
        job['local_lighting_provenance'] = {'plan': dict(job['lighting_plan']), 'steps': lighting,
                                          'pixel_source': 'original photograph',
                                          'engine': 'native masked Photoshop luminosity curves'}
    compiled = None
    if job.get('annotations'):
        annotation_path = Path(job['annotations'])
        if not annotation_path.is_absolute():
            annotation_path = (recipe_dir or Path.cwd()) / annotation_path
        annotation_path = annotation_path.resolve(strict=True)
        compiled = compile_annotations(read_json(annotation_path), expected_source=source)
        job['annotation_canvas'] = compiled['canvas']
        job['annotation_provenance'] = {
            'path': str(annotation_path), 'sha256': sha(annotation_path),
            'annotation_digest': compiled['annotation_digest'],
            'method': 'chatgpt_vision', 'native_canvas': compiled['canvas'],
            'curve_flattening_tolerance_native_px': compiled['curve_flattening_tolerance_native_px'],
        }
    # Never accept a caller-provided compiled region or canvas: resolve and verify
    # them from the reviewed source-bound annotation artifact ourselves.
    elif job.get('annotation_canvas') or job.get('annotation_provenance'):
        raise ValueError('Compiled annotation data requires its reviewed artifact')
    for step in job.get('steps', []):
        if not isinstance(step.get('name'), str) or not step['name'].strip():
            raise ValueError('Each adjustment needs a meaningful layer name')
        if step.get('kind') not in {'curves', 'hue_saturation'}:
            raise ValueError('Unsupported adjustment')
        if step.get('blend', 'normal') not in {'normal', 'luminosity', 'color'}:
            raise ValueError('Unsupported blend mode')
        if not 0 <= step.get('opacity', 100) <= 100:
            raise ValueError('Opacity outside 0..100')
        if step['kind'] == 'curves':
            if not isinstance(step.get('channels'), dict) or not step['channels']:
                raise ValueError('At least one curve channel is required')
            for channel, points in step['channels'].items():
                if channel not in {'composite', 'red', 'green', 'blue'} or len(points) < 2:
                    raise ValueError('Invalid curve channel or points')
                if any(len(p) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 255 for v in p) for p in points):
                    raise ValueError('Curve values outside 0..255')
                if any(points[i][0] >= points[i+1][0] or points[i][1] > points[i+1][1] for i in range(len(points)-1)):
                    raise ValueError('Curves must have strictly increasing input and monotonic output')
        else:
            for field, low, high in [('hue', -180, 180), ('saturation', -100, 100), ('lightness', -100, 100)]:
                if not isinstance(step.get(field, 0), int) or not low <= step.get(field, 0) <= high:
                    raise ValueError('Invalid hue/saturation/lightness value')
        region = step.get('region')
        if region:
            if region.get('kind') in {'subject', 'sky'}:
                raise ValueError('Photoshop automatic recognition is disabled; use ChatGPT annotations')
            if region.get('kind') == 'annotation':
                if not compiled or region.get('id') not in compiled['regions']:
                    raise ValueError('Region must refer to a reviewed ChatGPT annotation ID')
                if set(region) - {'kind', 'id', 'invert'}:
                    raise ValueError('Edit the annotation artifact to change geometry or feathering')
                step['region'] = dict(compiled['regions'][region['id']], invert=bool(region.get('invert', False)))
                continue
            if region.get('kind') not in {'polygon', 'ellipse'}:
                raise ValueError('Unsupported selection')
            if region['kind'] == 'polygon' and (len(region.get('points', [])) < 3 or any(len(p) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in p) for p in region['points'])):
                raise ValueError('Normalized polygon required')
            if region['kind'] == 'ellipse' and (len(region.get('bounds', [])) != 4 or any(not 0 <= v <= 1 for v in region['bounds']) or region['bounds'][0] >= region['bounds'][2] or region['bounds'][1] >= region['bounds'][3]):
                raise ValueError('Invalid ellipse bounds')
            if not 0 <= region.get('feather_fraction', .01) <= .2:
                raise ValueError('Invalid mask feather')
    job.pop('geometry_provenance', None)
    if 'straighten_transform' in job:
        raise ValueError('Use the reviewed straightening guide, not precompiled geometry')
    if job.get('straighten'):
        if stage != 'retouch' or job.get('crop'):
            raise ValueError('Straightening applies only to retouch and includes its own native crop')
        transform = compile_straightening(job['straighten'], compiled)
        job['straighten_transform'] = transform
        job['geometry_provenance'] = transform
    if job.get('crop'):
        b = job['crop']
        if len(b) != 4 or any(not 0 <= v <= 1 for v in b) or b[0] >= b[2] or b[1] >= b[3]:
            raise ValueError('Invalid crop')
        if (b[2]-b[0])*(b[3]-b[1]) < .7:
            raise ValueError('Crop discards more than 30% area; reconsider selection or explicitly adapt workflow')
    suffixes = ['_baseline.jpg'] if stage == 'prepare' else ((['.psd'] if job.get('save_psd', True) else []) + ['.jpg', '_execution.json'])
    for suffix in suffixes:
        destination = Path(str(output) + suffix)
        if destination == source:
            raise ValueError('Output would overwrite original')
        if destination.exists():
            raise FileExistsError(f'Existing output: {output}{suffix}; use a new version')
    job = dict(job, source=str(source), output_base=str(output), stage=stage)
    return job


def main():
    p = argparse.ArgumentParser()
    p.add_argument('recipe', type=Path, nargs='?')
    p.add_argument('--timeout', type=int, default=240, help='Bound COM call; unknown outcome blocks retries')
    p.add_argument('--recover-native', action='store_true', help='Bounded zero-document probe resolves an interrupted native call')
    p.add_argument('--quit-idle', action='store_true', help='Normal native quit only after a zero-document check')
    p.add_argument('--fresh-small-session', type=Path, metavar='PHOTOSHOP_EXE',
                   help='One fresh <=20.1MP job with9GiB reserve, then normal zero-document quit')
    p.add_argument('--validate-only', action='store_true')
    p.add_argument('--wait-startup-idle', action='store_true', help='Bounded read-only startup readiness; never retries a photo job')
    p.add_argument('--emit-jsx', type=Path, help='Emit validated native script for Photoshop File > Scripts > Browse')
    args = p.parse_args()
    if not 10 <= args.timeout <= 900:
        p.error('timeout must be 10..900 seconds')
    if args.quit_idle and (args.recover_native or args.wait_startup_idle):
        p.error('Quit cannot be combined with startup/recovery probes')
    if args.wait_startup_idle:
        with NativeGuard() as guard:
            result = guard.call({'operation': 'startup_idle_probe'}, timeout=50,
                                recovery=args.recover_native,
                                identity={'operation': 'bounded_startup_idle_probe'})
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.quit_idle:
        with NativeGuard() as guard:
            result = guard.call({'operation': 'quit_idle'}, timeout=30,
                                identity={'operation': 'normal_quit_if_idle'})
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.recover_native:
        with NativeGuard() as guard:
            result = guard.call(IDLE_PROBE, timeout=min(args.timeout, 30), recovery=True,
                                identity={'operation': 'recovery_idle_probe'})
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.recipe is None:
        p.error('recipe is required unless --recover-native is used')
    job = validate(json.loads(args.recipe.read_text(encoding='utf-8-sig')), args.recipe.resolve().parent)
    before = hashlib.sha256(Path(job['source']).read_bytes()).hexdigest()
    if args.validate_only:
        print(json.dumps({'valid': True, 'stage': job['stage'], 'source_sha256': before}, ensure_ascii=False))
        return
    recipe_fingerprint = fingerprint(args.recipe)
    engine = (Path(__file__).with_name('annotation_masks.jsx').read_text(encoding='utf-8') + '\n'
              + Path(__file__).with_name('retouch.jsx').read_text(encoding='utf-8'))
    # JSON is data consumed by ExtendScript; never inserted into a shell command.
    invocation = 'var RETOUCH_JOB = ' + json.dumps(job, ensure_ascii=True) + ';\n' + engine
    if args.emit_jsx:
        if args.emit_jsx.exists():
            raise FileExistsError('Use a fresh emitted script path')
        args.emit_jsx.parent.mkdir(parents=True, exist_ok=True)
        args.emit_jsx.write_text(invocation, encoding='utf-8')
        print(json.dumps({'native_script': str(args.emit_jsx.resolve()), 'source_sha256': before}, ensure_ascii=False))
        return
    # Reserve idle preflight, native work, normal quit and process exit. This
    # admission check intentionally does not block recovery or safe cleanup.
    session_admission = check_session(args.recipe, required_seconds=args.timeout + 180)
    disk = None if args.fresh_small_session else disk_preflight(job)
    session = None
    quit_result = None
    with NativeGuard() as guard:
        preflight = guard.call(IDLE_PROBE, timeout=30, identity={'operation': 'idle_preflight'})
        if args.fresh_small_session:
            disk, session = claim_fresh_small_session(job, args.fresh_small_session)
        native = guard.call(invocation, timeout=args.timeout,
                            identity={'recipe': str(args.recipe.resolve()), 'output_base': job['output_base'],
                                      'source_sha256': before, 'disk_preflight': disk})
        result = native['result']
        after = hashlib.sha256(Path(job['source']).read_bytes()).hexdigest()
        if before != after:
            raise RuntimeError('Original file changed')
        report = {'recipe': str(args.recipe.resolve()), 'source_sha256': before, 'original_unchanged': True,
              'photoshop_version': native['version'], 'result': result, 'visual_review': 'pending',
              'native_timeout_seconds': args.timeout, 'disk_preflight': disk,
              'session_admission': session_admission}
        report['evidence_version'] = 2
        report['recipe_fingerprint'] = recipe_fingerprint
        report['engine_sha256'] = hashlib.sha256(engine.encode('utf-8')).hexdigest()
        suffixes = ['_baseline.jpg'] if job['stage'] == 'prepare' else ['.jpg'] + (['.psd'] if job.get('save_psd', True) else [])
        report['output_fingerprints'] = [fingerprint(job['output_base'] + suffix) for suffix in suffixes]
        if session:
            report['fresh_small_session'] = session
            report['normal_idle_quit'] = {'status': 'pending'}
        if job['stage'] == 'retouch':
            report['saved_psd'] = job.get('save_psd', True)
        if job.get('annotation_provenance'):
            report['annotation_provenance'] = job['annotation_provenance']
        if job.get('local_lighting_provenance'):
            report['local_lighting_provenance'] = job['local_lighting_provenance']
        if job.get('geometry_provenance'):
            report['geometry_provenance'] = job['geometry_provenance']
        out = Path(job['output_base'] + '_execution.json')
        # A native save is a separate outcome from application shutdown.
        # Commit its receipt before quit so an exit failure never loses proof.
        atomic_json(out, report)
        if args.fresh_small_session:
            try:
                quit_result = guard.call({'operation':'quit_idle'}, timeout=30,
                                         identity={'operation':'normal_quit_after_one_small_job'})
            except BaseException as exc:
                report['normal_idle_quit'] = {'status': 'failed', 'error': repr(exc)}
                atomic_json(out, report)
                raise
            report['normal_idle_quit'] = quit_result
            atomic_json(out, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
