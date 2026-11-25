import json
import os
import sqlite3
import zipfile
from datetime import date
from io import BytesIO

import plotly.graph_objects as go
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

EPOCH = date(1970, 1, 1).toordinal()
PUSHUP_SEGMENT = 64
OUTPUT_FILE = 'health.html'
DRIVE_FILES = 'https://www.googleapis.com/drive/v3/files'

CYAN, MAGENTA, LIME, AMBER = '#00f0ff', '#ff2bd6', '#39ff14', '#ffb000'


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


def open_export(zip_bytes):
    with zipfile.ZipFile(BytesIO(zip_bytes)) as z:
        db_bytes = z.read('health_connect_export.db')
    db = sqlite3.connect(':memory:')
    db.deserialize(db_bytes)
    return db


def rolling_mean(values, days):
    result = []
    for d in sorted(values):
        window = [v for day, v in values.items() if 0 <= (d - day).days < days]
        result.append(sum(window) / len(window))
    return result


def download_latest_export(folder_id, key_json):
    creds = service_account.Credentials.from_service_account_info(
        json.loads(key_json), scopes=['https://www.googleapis.com/auth/drive.readonly'])
    session = AuthorizedSession(creds)
    resp = session.get(DRIVE_FILES, timeout=30, params={
        'q': f"'{folder_id}' in parents and trashed = false and name contains '.zip'",
        'orderBy': 'modifiedTime desc', 'pageSize': 1, 'fields': 'files(id)'})
    resp.raise_for_status()
    (latest,) = resp.json()['files']
    resp = session.get(f"{DRIVE_FILES}/{latest['id']}", params={'alt': 'media'}, timeout=120)
    resp.raise_for_status()
    return resp.content


def figure(title, *traces, y2=None):
    fig = go.Figure(traces)
    fig.update_layout(
        title=dict(text=title, font=dict(family='Orbitron', size=18, color=CYAN)),
        template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,240,255,0.03)',
        font=dict(family='Share Tech Mono', color='#9fb3c8'), height=380, bargap=0.15,
        margin=dict(l=50, r=50, t=60, b=40), hovermode='x unified',
        legend=dict(orientation='h', y=1.12, x=1, xanchor='right'),
        xaxis=dict(gridcolor='rgba(0,240,255,0.08)'), yaxis=dict(gridcolor='rgba(0,240,255,0.08)'))
    if y2:
        fig.update_layout(yaxis2=dict(title=y2, overlaying='y', side='right', showgrid=False))
    return fig


def bars(values, name, color, scale=1):
    days = sorted(values)
    return go.Bar(x=days, y=[values[d] / scale for d in days], name=name, marker_color=color, opacity=0.75)


def line(values, name, color, scale=1, **kwargs):
    days = sorted(values)
    return go.Scatter(x=days, y=[values[d] / scale for d in days], name=name, mode='lines',
                      line=dict(color=color, width=2.5, shape='spline'), **kwargs)


def kpi(label, value, color):
    return f'<div class="kpi" style="--c:{color}"><div class="v">{value}</div><div class="l">{label}</div></div>'


def render(db):
    pushups = daily_pushups(db)
    steps = daily_activity(db, 'steps_record_table', 'count')
    distance = daily_activity(db, 'distance_record_table', 'distance')
    active = daily_activity(db, 'active_calories_burned_record_table', 'energy')
    total = daily_activity(db, 'total_calories_burned_record_table', 'energy')

    cumulative, running = {}, 0
    for d in sorted(pushups):
        running += pushups[d]
        cumulative[d] = running
    best_day = max(pushups, key=pushups.get)
    steps_days = sorted(steps)

    figs = [
        figure('FEKVŐTÁMASZ // NAPI', bars(pushups, 'napi', CYAN),
               line(cumulative, 'összesen', MAGENTA, yaxis='y2'), y2='összesen'),
        figure('LÉPÉS // NAPI', bars(steps, 'napi', LIME),
               go.Scatter(x=steps_days, y=rolling_mean(steps, 7), name='7 napos átlag', mode='lines',
                          line=dict(color=AMBER, width=2.5, shape='spline'))),
        figure('TÁVOLSÁG // KM', bars(distance, 'napi km', AMBER, scale=1000)),
        figure('ENERGIA // KCAL', line(total, 'teljes', MAGENTA, scale=1000),
               line(active, 'aktív', CYAN, scale=1000, fill='tozeroy')),
    ]
    charts = ''.join(f'<div class="panel">{f.to_html(full_html=False, include_plotlyjs="cdn" if i == 0 else False)}</div>'
                     for i, f in enumerate(figs))
    kpis = ''.join([
        kpi('fekvőtámasz összesen', f'{running:,}'.replace(',', ' '), CYAN),
        kpi(f'legjobb nap · {best_day}', pushups[best_day], MAGENTA),
        kpi('edzésnap', len(pushups), CYAN),
        kpi('átlag lépés / nap', f'{sum(steps.values()) / len(steps):,.0f}'.replace(',', ' '), LIME),
        kpi('km összesen', f'{sum(distance.values()) / 1000:,.0f}'.replace(',', ' '), AMBER),
    ])
    last = max(pushups | steps)
    return TEMPLATE.format(kpis=kpis, charts=charts, last=last)


TEMPLATE = """<!DOCTYPE html>
<html lang="hu"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>HA5LA // BIOMETRICS</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;800&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
body {{ margin: 0; background: #05070d; color: #9fb3c8; font-family: 'Share Tech Mono', monospace;
  background-image: linear-gradient(rgba(0,240,255,.04) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(0,240,255,.04) 1px, transparent 1px);
  background-size: 40px 40px; }}
main {{ max-width: 1200px; margin: auto; padding: 32px 20px; }}
h1 {{ font-family: Orbitron, sans-serif; font-weight: 800; letter-spacing: .25em; color: #00f0ff; margin: 0;
  text-shadow: 0 0 12px rgba(0,240,255,.7); }}
.sub {{ color: #5c7085; letter-spacing: .15em; margin: 6px 0 28px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.kpi, .panel {{ background: rgba(10,16,28,.85); border: 1px solid rgba(0,240,255,.25); border-radius: 4px;
  clip-path: polygon(0 0, calc(100% - 14px) 0, 100% 14px, 100% 100%, 14px 100%, 0 calc(100% - 14px)); }}
.kpi {{ padding: 18px; border-color: var(--c); box-shadow: inset 0 0 24px -12px var(--c); }}
.kpi .v {{ font-family: Orbitron, sans-serif; font-size: 30px; color: var(--c); text-shadow: 0 0 10px var(--c); }}
.kpi .l {{ font-size: 12px; text-transform: uppercase; letter-spacing: .12em; margin-top: 6px; }}
.panel {{ padding: 8px; margin-bottom: 20px; }}
</style></head>
<body><main>
<h1>BIOMETRICS</h1>
<div class="sub">&gt; forrás: Health Connect · utolsó adat: {last}</div>
<div class="kpis">{kpis}</div>
{charts}
</main></body></html>
"""


if __name__ == '__main__':
    zip_bytes = download_latest_export(os.environ['HC_EXPORT_FOLDER_ID'], os.environ['GDRIVE_SA_KEY'])
    with open(OUTPUT_FILE, 'w') as f:
        f.write(render(open_export(zip_bytes)))
