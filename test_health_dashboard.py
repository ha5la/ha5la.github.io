import sqlite3
import unittest
from datetime import date

import health_dashboard as hd

PUSHUP = 64
SQUAT = 60
DAY = date(2026, 11, 24).toordinal() - date(1970, 1, 1).toordinal()


def make_db():
    db = sqlite3.connect(':memory:')
    db.executescript('''
        CREATE TABLE exercise_session_record_table (row_id INTEGER PRIMARY KEY, app_info_id INTEGER, local_date INTEGER);
        CREATE TABLE exercise_segments_table (parent_key INTEGER, segment_type INTEGER, repetitions_count INTEGER);
        CREATE TABLE health_data_category_priority_table (health_data_category INTEGER, app_id_priority_order TEXT);
        CREATE TABLE steps_record_table (app_info_id INTEGER, local_date INTEGER, count INTEGER);
    ''')
    return db


def add_session(db, local_date, *segments):
    row_id = db.execute('INSERT INTO exercise_session_record_table (app_info_id, local_date) VALUES (1, ?)',
                        (local_date,)).lastrowid
    db.executemany('INSERT INTO exercise_segments_table VALUES (?, ?, ?)',
                   [(row_id, kind, reps) for kind, reps in segments])


class DailyPushupsTest(unittest.TestCase):
    def test_should_sum_pushup_repetitions_per_local_day(self):
        db = make_db()
        add_session(db, DAY, (PUSHUP, 20), (PUSHUP, 30))
        add_session(db, DAY, (PUSHUP, 50))
        add_session(db, DAY + 1, (PUSHUP, 10))
        self.assertEqual(hd.daily_pushups(db), {date(2026, 11, 24): 100, date(2026, 11, 25): 10})

    def test_should_ignore_other_segment_types(self):
        db = make_db()
        add_session(db, DAY, (PUSHUP, 20), (SQUAT, 30))
        self.assertEqual(hd.daily_pushups(db), {date(2026, 11, 24): 20})


PHONE, FIT = 4, 6


def add_steps(db, app, local_date, count):
    db.execute('INSERT INTO steps_record_table VALUES (?, ?, ?)', (app, local_date, count))


class DailyActivityTest(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.db.execute("INSERT INTO health_data_category_priority_table VALUES (1, '1,4,6')")

    def test_should_take_each_day_from_highest_priority_source_only(self):
        add_steps(self.db, PHONE, DAY, 1000)
        add_steps(self.db, PHONE, DAY, 500)
        add_steps(self.db, FIT, DAY, 1400)
        add_steps(self.db, FIT, DAY + 1, 700)
        self.assertEqual(hd.daily_activity(self.db, 'steps_record_table', 'count'),
                         {date(2026, 11, 24): 1500, date(2026, 11, 25): 700})

    def test_should_ignore_sources_missing_from_priority_list(self):
        add_steps(self.db, PHONE, DAY, 1000)
        add_steps(self.db, 9, DAY + 1, 300)
        self.assertEqual(hd.daily_activity(self.db, 'steps_record_table', 'count'), {date(2026, 11, 24): 1000})


if __name__ == '__main__':
    unittest.main()
