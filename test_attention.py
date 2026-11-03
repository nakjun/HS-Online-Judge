import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import storage


def observation():
    return {'version': 1, 'started_at': '2026-11-03T02:00:00.000Z',
            'submitted_at': '2026-11-03T02:01:00.000Z',
            'away_count': 1, 'away_ms': 5000, 'hidden_count': 1, 'hidden_ms': 4000,
            'blur_count': 1, 'blur_ms': 5000, 'omitted_events': 0,
            'events': [{'type': 'blur', 'at': '2026-11-03T02:00:01.000Z'},
                       {'type': 'hidden', 'at': '2026-11-03T02:00:02.000Z'},
                       {'type': 'visible', 'at': '2026-11-03T02:00:06.000Z'},
                       {'type': 'focus', 'at': '2026-11-03T02:00:06.000Z'}]}


class AttentionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_db = storage.DB_PATH
        storage.DB_PATH = Path(self.directory.name) / 'judge.db'

    def tearDown(self):
        storage.DB_PATH = self.old_db
        self.directory.cleanup()

    def prepare(self):
        storage.init_db()
        with storage.connect() as db:
            db.execute("INSERT INTO students(student_id, name) VALUES ('001', '학생')")

    def test_saved_snapshot_and_legacy_missing_observations(self):
        self.prepare()
        original = observation()
        submission_id = storage.save_submission('001', 'a', 'print(1)', 'ACCEPTED', 1, 1,
                                                attention=original)
        original['away_count'] = 9
        self.assertEqual(storage.get_submission(submission_id)['attention'], observation())
        self.assertEqual(storage.list_submissions()[0]['attention'], observation())
        self.assertNotIn('attention_json', storage.list_submissions()[0])
        untracked = storage.save_submission('001', 'a', 'print(1)', 'WRONG_ANSWER', 0, 1)
        self.assertIsNone(storage.get_submission(untracked)['attention'])

    def test_invalid_payloads_become_untracked_and_extras_are_removed(self):
        for field, value in [('away_count', -1), ('hidden_ms', True), ('blur_count', '1'),
                             ('away_ms', float('nan')), ('away_ms', 31_536_000_001),
                             ('events', [{}]), ('events', observation()['events'] * 26),
                             ('started_at', 'bad'), ('submitted_at', '2026-11-03T02:01:00')]:
            with self.subTest(field=field, value=value):
                data = observation()
                data[field] = value
                self.assertIsNone(storage.normalize_attention(data))
        self.assertIsNone(storage.normalize_attention(None))
        self.assertIsNone(storage.normalize_attention({'version': True}))
        data = observation()
        data['other_tab_url'] = 'not collected'
        data['events'][0]['url'] = 'not stored'
        cleaned = storage.normalize_attention(data)
        self.assertNotIn('other_tab_url', cleaned)
        self.assertNotIn('url', cleaned['events'][0])
        zero = observation()
        for field in ('away_count', 'away_ms', 'hidden_count', 'hidden_ms', 'blur_count', 'blur_ms'):
            zero[field] = 0
        zero['events'] = []
        self.assertEqual(storage.normalize_attention(zero), zero)

    def test_existing_database_migration_preserves_rows(self):
        with closing(sqlite3.connect(storage.DB_PATH)) as db:
            db.execute('''CREATE TABLE submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL,
                problem_id TEXT NOT NULL, code TEXT NOT NULL, verdict TEXT NOT NULL,
                passed INTEGER NOT NULL, total INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            db.execute("INSERT INTO submissions(student_id,problem_id,code,verdict,passed,total) VALUES ('001','a','old','ACCEPTED',1,1)")
            db.commit()
        self.prepare()
        storage.init_db()  # Migration is safe to repeat.
        saved = storage.get_submission(1)
        self.assertEqual(saved['code'], 'old')
        self.assertIsNone(saved['attention'])


if __name__ == '__main__':
    unittest.main()
