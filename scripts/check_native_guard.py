"""Integration checks for actual COM timeout, durable stop and idle recovery.

Run only with Photoshop open and no documents or native jobs. The timeout test
uses a read-only 11-second ExtendScript sleep. It never touches photographs.
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from native_guard import NativeGuard, IDLE_PROBE, STATE


def main():
    evidence = []
    with NativeGuard() as guard:
        evidence.append(guard.call(IDLE_PROBE, timeout=30, recovery=True,
                                  identity={'operation': 'integration_idle'}))
        competing = subprocess.run([sys.executable, '-X', 'utf8', '-c',
            'from native_guard import NativeGuard;\nwith NativeGuard(): print("UNEXPECTED_CONCURRENT_ENTRY")'],
            cwd=__import__('pathlib').Path(__file__).parent, capture_output=True, text=True, timeout=10)
        assert competing.returncode != 0 and 'Another guarded Photoshop call' in competing.stderr, repr((competing.returncode, competing.stdout, competing.stderr))
        evidence.append({'exclusive_lock': 'passed'})
        began = time.monotonic()
        try:
            guard.call("(function(){if(app.documents.length!==0)throw new Error('No documents allowed');$.sleep(11000);return 'read-only sleep';}());",
                       timeout=10, identity={'operation': 'integration_benign_timeout'})
        except TimeoutError:
            evidence.append({'bounded_timeout': 'passed', 'seconds': round(time.monotonic()-began, 2)})
        else:
            raise AssertionError('The 11-second call should time out at 10 seconds')
    assert json.loads(STATE.read_text('utf-8'))['status'] == 'outcome_unknown'
    with NativeGuard() as guard:
        try:
            guard.call(IDLE_PROBE, timeout=30)
        except RuntimeError as exc:
            assert 'unresolved' in str(exc)
            evidence.append({'durable_retry_block': 'passed'})
        else:
            raise AssertionError('Uncertain call must block subsequent submission')
        evidence.append(guard.call(IDLE_PROBE, timeout=30, recovery=True,
                                  identity={'operation': 'integration_recovery'}))
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
