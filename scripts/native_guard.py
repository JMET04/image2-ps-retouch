"""Bounded, globally serialized Photoshop COM calls with durable uncertainty.

Timing out a COM client does NOT cancel Photoshop. Unknown outcomes block the
next job until a separately bounded zero-document probe succeeds.
"""
from __future__ import annotations
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import subprocess
import time
import msvcrt

ROOT = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexPhotoRetouch'
STATE = ROOT / 'native-state.json'
SESSION_BUDGET = ROOT / 'single-session-budget.json'


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.writing')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def _read_idle(ps, pipe, deadline):
    """Only a read-only zero-document probe may retry a rejected COM call."""
    import pythoncom
    attempts = 0
    last_notice = 0
    while True:
        attempts += 1
        try:
            return ps.DoJavaScript(IDLE_PROBE)
        except pythoncom.com_error as exc:
            remaining = deadline - time.monotonic()
            if exc.hresult != -2147417846 or remaining <= 0:
                raise
            if attempts >= last_notice + 10:
                pipe.send({'status': 'checkpoint', 'phase': 'read_only_idle_rejected',
                           'attempts': attempts, 'remaining_seconds': round(remaining, 1)})
                last_notice = attempts
            time.sleep(min(.3, remaining))


def _worker(pipe, script, verified_version=None):
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        idle_deadline = time.monotonic() + 24
        if isinstance(script, dict) and script.get('operation') == 'startup_idle_probe':
            startup_deadline = time.monotonic() + 45
            while True:
                try:
                    ps = win32com.client.GetActiveObject('Photoshop.Application')
                    break
                except pythoncom.com_error as exc:
                    if exc.hresult != -2147221021 or time.monotonic() >= startup_deadline:
                        raise
                    time.sleep(.3)
            script = IDLE_PROBE  # only the read-only probe waits for registration
            idle_deadline = startup_deadline
        else:
            ps = win32com.client.GetActiveObject('Photoshop.Application')
        pipe.send({'status': 'connected'})
        if isinstance(script, dict) and script.get('operation') == 'quit_idle':
            pipe.send({'status': 'checkpoint', 'phase': 'idle_probe'})
            idle = _read_idle(ps, pipe, idle_deadline)
            version = str(idle).split(' ')[1]
            pipe.send({'status': 'checkpoint', 'phase': 'idle_verified_before_quit', 'documents': 0})
            ps.Quit()  # zero documents verified in the same serialized worker
            result = 'Normal Photoshop quit requested after documents=0'
        elif script == IDLE_PROBE:
            # Control readiness must be established by the actual read-only
            # script, without an unrelated Version-property call beforehand.
            pipe.send({'status': 'checkpoint', 'phase': 'idle_probe'})
            result = _read_idle(ps, pipe, idle_deadline)
            version = str(result).split(' ')[1]
        else:
            if verified_version is None:
                pipe.send({'status': 'checkpoint', 'phase': 'version_query'})
                version = str(ps.Version)
            else:
                version = str(verified_version)
            pipe.send({'status': 'checkpoint', 'phase': 'native_script'})
            result = ps.DoJavaScript(script)
        pipe.send({'status': 'complete', 'result': result, 'version': version})
    except BaseException as exc:
        pipe.send({'status': 'error', 'error': repr(exc)})
    finally:
        pipe.close()


class NativeGuard:
    def __enter__(self):
        ROOT.mkdir(parents=True, exist_ok=True)
        lock_path = ROOT / 'photoshop.lock'
        try:
            with lock_path.open('xb') as initial:
                initial.write(b'0')
        except FileExistsError:
            pass
        # Do not read the byte before acquiring: Windows forbids even a read
        # when the previous process owns that region.
        self.handle = lock_path.open('r+b', buffering=0)
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.handle.close()
            raise RuntimeError('Another guarded Photoshop call is running; do not submit concurrently')
        self.prior = json.loads(STATE.read_text('utf-8')) if STATE.exists() else {}
        self.verified_version = None
        return self

    def __exit__(self, *unused):
        self.handle.seek(0)
        msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        self.handle.close()

    def call(self, script: str, *, timeout=240, identity=None, recovery=False):
        if not recovery and self.prior.get('status') in {'running', 'outcome_unknown', 'native_error'}:
            raise RuntimeError('Prior Photoshop outcome is unresolved. Inspect the application, then run --recover-native; no automatic retry. ' + str(STATE))
        manifest = {'status': 'running', 'pid': os.getpid(), 'started_epoch': time.time(),
                    'identity': identity, 'timeout_seconds': timeout,
                    'recovery_probe': recovery}
        atomic_json(STATE, manifest)
        context = mp.get_context('spawn')
        receiving, sending = context.Pipe(duplex=False)
        worker = context.Process(target=_worker, args=(sending, script, self.verified_version), daemon=True)
        worker.start()
        sending.close()
        deadline = time.monotonic() + timeout
        final = None
        last_notice = 0
        try:
            while time.monotonic() < deadline:
                if receiving.poll(.2):
                    try:
                        event = receiving.recv()
                    except EOFError:
                        break
                    if event['status'] == 'checkpoint':
                        manifest['last_checkpoint'] = event
                        atomic_json(STATE, manifest)
                    elif event['status'] != 'connected':
                        final = event
                        break
                if not worker.is_alive():
                    # A short probe can send both messages and exit before
                    # the parent consumes its initial connected notification.
                    # Drain its terminal event instead of reporting uncertainty.
                    while receiving.poll():
                        try:
                            event = receiving.recv()
                        except EOFError:
                            break
                        if event['status'] == 'checkpoint':
                            manifest['last_checkpoint'] = event
                            atomic_json(STATE, manifest)
                        elif event['status'] != 'connected':
                            final = event
                    break
                elapsed = round(timeout - (deadline-time.monotonic()))
                if elapsed >= last_notice + 30:
                    print(json.dumps({'native_call': 'waiting', 'seconds': elapsed, 'identity': identity}, ensure_ascii=False), flush=True)
                    last_notice = elapsed
            if final is None:
                if worker.is_alive():
                    worker.terminate()  # only our Python client; never kill Photoshop
                worker.join(5)
                atomic_json(STATE, dict(manifest, status='outcome_unknown',
                                       note='Client ended; Photoshop may still be working. Inspect before recovery.'))
                raise TimeoutError('Photoshop result unknown; queue locked against retries: ' + str(STATE))
            worker.join(5)
            if final['status'] == 'error':
                atomic_json(STATE, dict(manifest, status='native_error', error=final['error']))
                raise RuntimeError(final['error'])
            atomic_json(STATE, dict(manifest, status='complete', result=final['result'],
                                   completed_epoch=time.time(), version=final['version']))
            self.prior = dict(manifest, status='complete')
            self.verified_version = final['version']
            return final
        finally:
            receiving.close()
            if worker.is_alive():
                worker.terminate()
                worker.join(5)


def disk_preflight(job: dict, minimum_gib=16):
    control_drive = Path(os.environ['LOCALAPPDATA']).anchor
    control_free = shutil.disk_usage(control_drive).free
    if control_free < 512 * 1024**2:
        raise RuntimeError(f'Control/cache disk {control_drive} has only {control_free/1024**2:.0f} MiB free; minimum reserve is 512 MiB')
    # Output disk is a known project dependency; do not guess scratch settings.
    drive = Path(job['output_base']).anchor
    free = shutil.disk_usage(drive).free
    if free < minimum_gib * 1024**3:
        raise RuntimeError(f'Output disk {drive} has only {free/1024**3:.1f} GiB free; minimum reserve is {minimum_gib} GiB')
    return {'output_drive': drive, 'free_bytes': free, 'minimum_gib': minimum_gib}


def claim_fresh_small_session(job: dict, photoshop_executable: Path):
    """Opt-in budget for one bounded <=20.1MP, <=12-step job then normal exit.

    Call under NativeGuard's lock. A fresh PID and source-bound dimensions are
    mandatory. A claim is durable even if the job later fails or times out.
    """
    canvas = job.get('annotation_canvas')
    if (job.get('stage') != 'retouch' or not job.get('annotation_provenance')
            or not canvas or canvas[0]*canvas[1] > 20_100_000
            or len(job['steps']) > 12):
        raise ValueError('Fresh small-session budget requires source-bound <=20.1MP, <=12-step retouch')
    executable = photoshop_executable.resolve(strict=True)
    if executable.name.lower() != 'photoshop.exe':
        raise ValueError('Pass the verified Photoshop executable')
    query = "@(Get-Process -Name Photoshop -ErrorAction SilentlyContinue | Select-Object Id,Path,@{Name='started_epoch';Expression={([DateTimeOffset]$_.StartTime).ToUnixTimeSeconds()}}) | ConvertTo-Json -Compress"
    r = subprocess.run(['powershell.exe', '-NoProfile', '-Command', query],
                       capture_output=True, text=True, encoding='utf-8',
                       timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    r.check_returncode()
    rows = json.loads(r.stdout.strip() or '[]')
    rows = [rows] if isinstance(rows, dict) else rows
    if len(rows) != 1 or Path(rows[0]['Path']).resolve() != executable:
        raise RuntimeError('Exactly one newly launched verified Photoshop instance is required')
    process = rows[0]
    age = time.time()-process['started_epoch']
    if age < 0 or age > 60:
        raise RuntimeError('Small-session budget requires Photoshop launched within the last60 seconds')
    key = str(process['Id'])+':'+str(process['started_epoch'])
    prior = json.loads(SESSION_BUDGET.read_text('utf-8')) if SESSION_BUDGET.exists() else {}
    if prior.get('session_key') == key:
        raise RuntimeError('This Photoshop session already claimed its one job; normal idle quit and restart required')
    disk = disk_preflight(job, minimum_gib=9)
    claim = dict(session_key=key, process=process, process_age_seconds=round(age, 2),
                 native_canvas=canvas, step_count=len(job['steps']), minimum_gib=9,
                 one_job_only=True, normal_quit_after_success=True,
                 basis='Project single-session scratch observed about4.35GB;9GiB reserve plus zero-document/fresh-process checks. Not the Adobe100GB recommendation.')
    atomic_json(SESSION_BUDGET, claim)
    return disk, claim


IDLE_PROBE = "(function(){if(app.documents.length!==0)throw new Error('Recovery requires zero documents; do not close user documents automatically');return 'IDLE '+app.version+' documents=0';}());"
