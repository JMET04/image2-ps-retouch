"""Read-only admission control for a user-limited project session.

Never kills Photoshop or interrupts a save. Cleanup/recovery calls do not use
this gate; callers reserve their whole bounded lifecycle before starting work.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3


class SessionStopped(RuntimeError):
    pass


def find_policy(context):
    path = Path(context).resolve()
    if not path.is_dir():
        path = path.parent
    for directory in (path, *path.parents):
        candidate = directory / '.retouch-session.json'
        if candidate.is_file():
            return candidate
    return None


def current_model(database, thread_id):
    # mode=ro avoids creating an absent DB, and timeout bounds lock contention.
    try:
        uri = Path(database).resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            row = conn.execute('SELECT model FROM threads WHERE id=?', (thread_id,)).fetchone()
        return row[0] if row else None
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def check_session(context, required_seconds=0, now=None):
    if not isinstance(required_seconds, (int, float)) or not 0 <= required_seconds <= 86400:
        raise ValueError('Invalid lifecycle reserve')
    policy = find_policy(context)
    if policy is None:
        return {'decision': 'no_session_limit'}
    try:
        data = json.loads(policy.read_text(encoding='utf-8-sig'))
        if data['schema_version'] != 1 or data['resume_model'] != 'gpt-6.1-sol':
            raise ValueError('Unsupported session policy')
        deadline = datetime.fromisoformat(data['deadline'])
        if deadline.utcoffset() is None or not data['thread_id'] or not data['model_state_db']:
            raise ValueError('Timezone, thread and model database are required')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SessionStopped(f'Invalid session policy {policy}: {exc}') from exc
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError('Current time must include timezone')
    model = current_model(data['model_state_db'], data['thread_id'])
    result = {'policy': str(policy), 'deadline': deadline.isoformat(), 'model': model,
              'required_seconds': required_seconds,
              'seconds_remaining': round((deadline-now).total_seconds(), 1)}
    if model == data['resume_model']:
        return dict(result, decision='model_switched')
    if now >= deadline or now + timedelta(seconds=required_seconds) > deadline:
        raise SessionStopped('Session limit: no new job admitted; preserve saved outputs and '
                             'finish safe cleanup. ' + json.dumps(result, ensure_ascii=False))
    return dict(result, decision='within_window')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--reserve-seconds', type=int, default=0)
    args = parser.parse_args()
    try:
        result = check_session(args.context, args.reserve_seconds)
    except SessionStopped as exc:
        parser.exit(3, str(exc)+'\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
