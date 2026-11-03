import tempfile
import unittest
from pathlib import Path

import storage


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_db = storage.DB_PATH
        storage.DB_PATH = Path(self.directory.name) / 'judge.db'
        storage.init_db()
        self.weeks = [{'id': 'week-1', 'title': '1주차'}, {'id': 'week-10', 'title': '10주차'},
                      {'id': 'empty', 'title': '빈 주차'}]
        self.problems = [{'id': 'old', 'title': '기존 문제'},
                         {'id': 'a', 'week_id': 'week-10', 'title': '문제 A'},
                         {'id': 'b', 'week_id': 'week-10', 'title': '문제 B'}]
        with storage.connect() as db:
            db.executemany('INSERT INTO students(student_id, name) VALUES (?, ?)',
                           [(f'{i:03}', f'학생{i:03}') for i in range(105)])

    def tearDown(self):
        storage.DB_PATH = self.old_db
        self.directory.cleanup()

    def submit(self, sid, problem, verdict='ACCEPTED', code='print("원문")\n\n'):
        return storage.save_submission(sid, problem, code, verdict, 1, 1)

    def test_week_sorting_before_pagination_and_distinct_accepted(self):
        for _ in range(5):
            self.submit('104', 'a')
        self.submit('104', 'a', 'WRONG_ANSWER')
        self.submit('103', 'a')
        self.submit('103', 'b')
        for _ in range(10):
            self.submit('000', 'old')
        self.submit('001', 'deleted-problem')
        result = storage.progress_page(self.weeks, self.problems, week_id='week-10',
                                       sort='attempts', direction='desc', limit=1)
        self.assertEqual(result['total_students'], 105)
        self.assertEqual([w['id'] for w in result['weeks']], ['week-10'])
        row = result['rows'][0]
        self.assertEqual((row['student_id'], row['attempts'], row['accepted']), ('104', 6, 1))
        self.assertEqual(row['weeks'][0]['submitted'], 1)
        self.assertEqual(row['weeks'][0]['attempts'], 6)
        self.assertTrue(row['weeks'][0]['problems'][0]['accepted'])
        self.assertEqual(row['weeks'][0]['problems'][0]['latest_verdict'], 'WRONG_ANSWER')
        second = storage.progress_page(self.weeks, self.problems, week_id='week-10',
                                       sort='attempts', direction='desc', offset=1, limit=1)
        self.assertEqual(second['rows'][0]['student_id'], '103')
        accepted = storage.progress_page(self.weeks, self.problems, week_id='week-10',
                                         sort='accepted', direction='desc')
        self.assertEqual(accepted['rows'][0]['student_id'], '103')
        self.assertEqual(accepted['rows'][0]['accepted'], 2)
        old = storage.progress_page(self.weeks, self.problems, week_id='week-1', sort='attempts', direction='desc')
        self.assertEqual(old['rows'][0]['attempts'], 10)

    def test_identity_sort_search_empty_week_and_validation(self):
        by_id = storage.progress_page(self.weeks, self.problems, sort='student_id', direction='desc', limit=2)
        self.assertEqual([r['student_id'] for r in by_id['rows']], ['104', '103'])
        by_name = storage.progress_page(self.weeks, self.problems, query='학생10', sort='name', direction='desc')
        self.assertEqual(by_name['total_students'], 5)
        self.assertEqual(by_name['rows'][0]['student_id'], '104')
        self.assertEqual(storage.progress_page(self.weeks, self.problems, query='%')['total_students'], 0)
        empty = storage.progress_page(self.weeks, self.problems, week_id='empty', sort='accepted', direction='desc')
        self.assertTrue(all(r['attempts'] == r['accepted'] == 0 for r in empty['rows']))
        self.assertEqual(empty['rows'][0]['weeks'][0]['total'], 0)
        for options in ({'week_id': 'missing'}, {'sort': 'name; DROP TABLE students'}, {'direction': 'invalid'}):
            with self.assertRaises(ValueError):
                storage.progress_page(self.weeks, self.problems, **options)

    def test_accepted_source_preserved_and_scoped_to_student(self):
        source = '  # 공백과 줄바꿈\nprint("원문")\n\n'
        self.submit('000', 'a', code='old')
        latest = self.submit('000', 'a', code=source)
        self.submit('000', 'a', 'WRONG_ANSWER', code='broken')
        self.submit('001', 'a', code='other student')
        self.assertEqual(storage.accepted_codes('000'),
                         [{'problem_id': 'a', 'submission_id': latest, 'code': source}])
        self.assertEqual(storage.accepted_codes('002'), [])


if __name__ == '__main__':
    unittest.main()
