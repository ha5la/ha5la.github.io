from datetime import date

EPOCH = date(1970, 1, 1).toordinal()
PUSHUP_SEGMENT = 64


def to_date(local_date):
    return date.fromordinal(EPOCH + local_date)


def daily_pushups(db):
    rows = db.execute('''
        SELECT s.local_date, SUM(g.repetitions_count)
        FROM exercise_session_record_table s JOIN exercise_segments_table g ON g.parent_key = s.row_id
        WHERE g.segment_type = ?
        GROUP BY s.local_date''', (PUSHUP_SEGMENT,))
    return {to_date(d): reps for d, reps in rows}


def daily_activity(db, table, column):
    (order,) = db.execute(
        'SELECT app_id_priority_order FROM health_data_category_priority_table WHERE health_data_category = 1').fetchone()
    priority = {int(app): rank for rank, app in enumerate(order.split(','))}
    best = {}
    for app, local_date, total in db.execute(
            f'SELECT app_info_id, local_date, SUM({column}) FROM {table} GROUP BY app_info_id, local_date'):
        if app in priority and (local_date not in best or priority[app] < best[local_date][0]):
            best[local_date] = (priority[app], total)
    return {to_date(d): total for d, (_, total) in best.items()}
