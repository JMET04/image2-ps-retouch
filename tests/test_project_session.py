import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from project_session import check_session, SessionStopped


class ProjectSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'state.sqlite'
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('CREATE TABLE threads (id TEXT, model TEXT)')
            conn.execute('INSERT INTO threads VALUES (?,?)', ('test-thread', 'gpt-6-astra'))
            conn.commit()
        self.deadline = datetime(2026, 10, 15, 14, 51, 26, tzinfo=timezone(timedelta(hours=8)))
        self.config = self.root / '.retouch-session.json'
        self.data = dict(schema_version=1, thread_id='test-thread', deadline=self.deadline.isoformat(),
                         resume_model='gpt-6.1-sol', model_state_db=str(self.db))
        self.config.write_text(json.dumps(self.data))
        self.context = self.root / 'recipes' / 'photo.json'

    def check(self, seconds_left, reserve=0):
        return check_session(self.context, required_seconds=reserve,
                             now=self.deadline-timedelta(seconds=seconds_left))

    def test_before_deadline_with_sufficient_reserve(self):
        self.assertEqual(self.check(800, 720)['decision'], 'within_window')

    def test_rejects_insufficient_time_without_starting_anything(self):
        with self.assertRaises(SessionStopped):
            self.check(719, 720)

    def test_exact_deadline_and_past_deadline_stop(self):
        for seconds in (0, -1, -3600):
            with self.assertRaises(SessionStopped):
                self.check(seconds)

    def test_sol_releases_limit_even_after_deadline(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('UPDATE threads SET model=?', ('gpt-6.1-sol',))
            conn.commit()
        self.assertEqual(self.check(-500, 720)['decision'], 'model_switched')

    def test_unknown_model_and_missing_database_fail_closed_after_deadline(self):
        self.db.unlink()
        with self.assertRaises(SessionStopped):
            self.check(-1)
        self.assertFalse(self.db.exists(), 'Read-only query must never create a database')

    def test_unrelated_project_is_unrestricted(self):
        self.config.unlink()
        self.assertEqual(self.check(-1)['decision'], 'no_session_limit')

    def test_malformed_policy_is_rejected(self):
        self.config.write_text('{')
        with self.assertRaises(SessionStopped):
            self.check(900)

    def test_naive_deadline_rejected(self):
        self.data['deadline'] = '2026-10-15T14:51:26'
        self.config.write_text(json.dumps(self.data))
        with self.assertRaises(SessionStopped):
            self.check(900)

    def test_negative_reserve_rejected(self):
        with self.assertRaises(ValueError):
            self.check(900, -1)


if __name__ == '__main__':
    unittest.main()
