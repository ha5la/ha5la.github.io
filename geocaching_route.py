"""Egynapos geoládázó útvonal tervezése a még meg nem talált geocaching.hu ládákhoz.

Használat:
  GEOCACHING_HU_UID=<id> uv run geocaching_route.py --date 2026-10-11 --return-by 19:00 --out tura.gpx
"""
import argparse
import math
import os
import re
import time
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape

import numpy as np
import requests

API = 'https://api.geocaching.hu'
OSRM = 'https://router.project-osrm.org'
OVERPASS = 'https://overpass-api.de/api/interpreter'
HUNGARY = dict(lat1=45.7, lat2=48.6, lon1=16.1, lon2=22.9)
PARKABLE = {'residential', 'unclassified', 'tertiary', 'secondary', 'living_street', 'service'}
MIN_DIST = 50  # m, ennyire legyen a túra pontja minden ládától, hogy ne takarja az appban
TYPES = {'1': 'Hagyományos', '2': 'Multi', '3': 'Virtuális', '4': 'Esemény típusú (állandó)'}


def meters(p, q):
    k = math.cos(math.radians(p[0]))
    return math.hypot((p[0] - q[0]) * 111320, (p[1] - q[1]) * 111320 * k)


def sun_times(lat, lon, day):
    """Napkelte és napnyugta helyi (Europe/Budapest) időben, NOAA közelítéssel."""
    n = day.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(math.radians(lat)) * math.cos(decl))
                                - math.tan(math.radians(lat)) * math.tan(decl)))
    # nyári időszámítás: március utolsó vasárnapjától október utolsó vasárnapjáig
    last_sunday = lambda m: max(date(day.year, m, d) for d in range(25, 32) if date(day.year, m, d).weekday() == 6)
    tz = 2 if last_sunday(3) <= day < last_sunday(10) else 1
    midnight = datetime(day.year, day.month, day.day)
    at = lambda minutes_utc: midnight + timedelta(minutes=minutes_utc + 60 * tz)
    return at(720 - 4 * (lon + ha) - eqt), at(720 - 4 * (lon - ha) - eqt)


def service_min(c):
    """Becsült idő egy ládánál (parkolás, séta oda-vissza, keresés), vagy None ha nem éri meg."""
    t, d, terrain = c['type'], float(c['difficulty_rating']), float(c['terrain_rating'])
    length = int(c['length']) if c['length'] else None
    if t == '2':
        n = int(c['multi'] or 2)
        length = length if length is not None else 1500 * n
        if n > 4 or length > 4000 or d > 2.5:
            return None
        return 10 + 12 * n + 2 * length / 70
    length = length if length is not None else 300
    if length > 2500 or d > 3 or terrain > 3.5 or re.search(r'\d', c['needs_maintenance']):
        return None
    return 6 + 2 * length / 70 + 4 * (d - 1) + 3 * max(0, terrain - 2) + (2 if t == '3' else 0)


def fetch_unfound(uid):
    fields = 'id,nickname,waypoint,type,lat,lon,difficulty_rating,terrain_rating,multi,length,state,needs_maintenance'
    return requests.get(f'{API}/cachesbyarea', params=dict(HUNGARY, userid=uid, status='1', type='1,2,3,4',
                                                            found='false', fields=fields), timeout=60).json()


def haversine_times(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    a = (np.sin((la[None] - la[:, None]) / 2) ** 2
         + np.cos(la[:, None]) * np.cos(la[None]) * np.sin((lo[None] - lo[:, None]) / 2) ** 2)
    km = 2 * 6371 * np.arcsin(np.sqrt(a)) * 1.3
    t = 3 + np.where(km < 5, km / 35, np.where(km < 30, 5 / 35 + (km - 5) / 60, 5 / 35 + 25 / 60 + (km - 30) / 90)) * 60
    np.fill_diagonal(t, 0)
    return t


def osrm_times(points):
    coords = ';'.join(f'{lon},{lat}' for lat, lon in points)
    js = requests.get(f'{OSRM}/table/v1/driving/{coords}?annotations=duration,distance', timeout=120).json()
    t = np.array(js['durations']) / 60 * 1.15 + 3
    np.fill_diagonal(t, 0)
    return t, np.array(js['distances']) / 1000


def plan(T, svc, fits, seeds, swaps=True):
    """Orienteering heurisztika: a 0. pont az otthon; fits(odaút, terepi idő, hazaút) dönti el, belefér-e."""
    n = len(svc)

    def field(rt):
        return sum(T[a, b] for a, b in zip(rt, rt[1:])) + svc[rt].sum()

    def total(rt):
        return T[0, rt[0]] + field(rt) + T[rt[-1], 0]

    def ok(rt):
        return fits(T[0, rt[0]], field(rt), T[rt[-1], 0])

    def two_opt(rt):
        improved = True
        while improved:
            improved = False
            for i in range(len(rt) - 1):
                for j in range(i + 1, len(rt)):
                    nr = rt[:i] + rt[i:j + 1][::-1] + rt[j + 1:]
                    if total(nr) < total(rt) - 1e-6 and ok(nr):
                        rt, improved = nr, True
        return rt

    def grow(rt):
        while True:
            best = None
            for c in range(1, n):
                if c in rt:
                    continue
                for k in range(len(rt) + 1):
                    nr = rt[:k] + [c] + rt[k:]
                    if ok(nr) and (best is None or total(nr) < best[0]):
                        best = (total(nr), nr)
            if best is None:
                return rt
            rt = two_opt(best[1])

    key = lambda rt: (len(rt), -total(rt))
    best = max((grow([s]) for s in seeds if ok([s])), key=key, default=None)
    if best is None:
        return [], 0
    for i in range(len(best) if swaps else 0):  # egy láda cseréje jobbakra
        rt = grow(best[:i] + best[i + 1:])
        if key(rt) > key(best):
            best = rt
    return best, total(best)


def coarse_regions(cands, home, fits, count):
    """Gyors, légvonalas becslés az egész országra; a legjobb `count` megye útvonala."""
    lat = np.array([home[0]] + [float(c['lat']) for c in cands])
    lon = np.array([home[1]] + [float(c['lon']) for c in cands])
    T = haversine_times(lat, lon)
    svc = np.array([0] + [c['service'] for c in cands])
    regions = {}
    seeds = [s for s in np.argsort(-(T[1:, 1:] < 15).sum(1)) + 1 if fits(T[0, s], svc[s], T[s, 0])]
    for seed in seeds[:100]:
        near = [0] + [int(i) for i in np.argsort(T[seed])[:60] if i != 0]
        rt, _ = plan(T[np.ix_(near, near)], svc[near], fits, [near.index(seed)], swaps=False)
        if not rt:
            continue
        rt = [near[i] for i in rt]
        state = cands[rt[len(rt) // 2] - 1]['state']
        if state not in regions or len(rt) > len(regions[state]):
            regions[state] = rt
    best = sorted(regions.items(), key=lambda kv: -len(kv[1]))[:count]
    return {state: [cands[i - 1] for i in rt] for state, rt in best}


def refine(cands, route, home, fits):
    """Valós (OSRM) menetidőkkel újratervez az előzetes útvonal környékén."""
    dist = lambda c: min(meters((float(c['lat']), float(c['lon'])), (float(r['lat']), float(r['lon']))) for r in route)
    pool = sorted(cands, key=lambda c: dist(c) / 1000 + c['service'] / 10)[:98]
    T, km = osrm_times([home] + [(float(c['lat']), float(c['lon'])) for c in pool])
    svc = np.array([0] + [c['service'] for c in pool])
    rt, total = plan(T, svc, fits, range(1, len(svc), 3))
    if not rt:
        return [], 0, 0, 0
    legs = [T[0, rt[0]]] + [T[a, b] for a, b in zip(rt, rt[1:])]
    dist_km = km[0, rt[0]] + sum(km[a, b] for a, b in zip(rt, rt[1:])) + km[rt[-1], 0]
    return [dict(pool[i - 1], drive=d) for i, d in zip(rt, legs)], T[rt[-1], 0], total, dist_km


def road_point(cache, ways, caches):
    """A ládához legközelebbi parkolásra alkalmas útpont, ami minden ládától legalább MIN_DIST-re van."""
    best = None
    for w in ways:
        if w['tags'].get('highway') not in PARKABLE:
            continue
        g = [(p['lat'], p['lon']) for p in w['geometry']]
        for a, b in zip(g, g[1:]):
            steps = max(1, int(meters(a, b) / 2))
            for k in range(steps + 1):
                p = (a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps)
                d = meters(p, cache)
                if (best is None or d < best[0]) and min(meters(p, c) for c in caches) >= MIN_DIST:
                    best = (d, p)
    return best and best[1]


def overpass_ways(positions, radius=500):
    query = '[out:json][timeout:120];(' + ''.join(f'way(around:{radius},{la},{lo})[highway];' for la, lo in positions)
    query += ');out tags geom;'
    for wait in (10, 30, 60, 120, None):
        r = requests.post(OVERPASS, data={'data': query}, headers={'User-Agent': 'geocaching_route.py'}, timeout=180)
        if r.ok:
            return r.json()['elements']
        if wait is None:
            r.raise_for_status()
        print(f'Overpass: HTTP {r.status_code}, újrapróbálás {wait} mp múlva')
        time.sleep(wait)


def route_points(route, caches):
    """A túra pontjai: a láda kijelölt parkolója, vagy a legközelebbi alkalmas út."""
    pts = requests.get(f'{API}/points', params={'id_list': ','.join(c['id'] for c in route),
                                                'fields': 'id,name,description,lat,lon'}, timeout=30).json()
    positions = [(float(c['lat']), float(c['lon'])) for c in route]
    ways = overpass_ways(positions)
    result = {}
    for c, pos in zip(route, positions):
        near = [q for q in caches if meters(q, pos) < 1000]
        parking = [(float(p['lat']), float(p['lon'])) for p in pts
                   if p['id'] == c['id'] and re.search('parkol', p['name'] + p['description'], re.I)]
        parking = [q for q in parking if min(meters(q, x) for x in near) >= MIN_DIST]
        if parking:
            result[c['waypoint']] = parking[0], 'parkoló'
        elif p := road_point(pos, ways, near):
            result[c['waypoint']] = p, 'közút'
        else:
            raise RuntimeError(f'Nincs út a {c["waypoint"]} közelében')
    return result


def write_gpx(path, title, home, route, points, start):
    t = start
    wpts, rtepts = [], []
    for i, c in enumerate(route, 1):
        t += timedelta(minutes=float(c['drive']))
        (lat, lon), src = points[c['waypoint']]
        desc = f"{i:02d}. {t:%H:%M} {TYPES[c['type']]} D{c['difficulty_rating']}/T{c['terrain_rating']} {c['nickname']}"
        url = f"https://geocaching.hu/caches.geo?id={c['id']}"
        wpts.append(f'<wpt lat="{lat:.6f}" lon="{lon:.6f}"><name>{escape(c["waypoint"])}</name><desc>{escape(desc)}</desc>'
                    f'<link href="{escape(url)}"><text>{escape(c["nickname"])}</text></link><sym>Parking Area</sym></wpt>')
        rtepts.append(f'<rtept lat="{lat:.6f}" lon="{lon:.6f}"><name>{escape(c["waypoint"])} P</name><desc>{src}</desc></rtept>')
        t += timedelta(minutes=float(c['service']))
    h = f'<rtept lat="{home[0]}" lon="{home[1]}"><name>Otthon</name></rtept>'
    with open(path, 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<gpx version="1.1" creator="geocaching_route.py" xmlns="http://www.topografix.com/GPX/1/1">\n'
                f'<metadata><name>{escape(title)}</name></metadata>\n' + '\n'.join(wpts) +
                f'\n<rte><name>{escape(title)}</name>{h}{"".join(rtepts)}{h}</rte>\n</gpx>\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--uid', type=int, default=os.environ.get('GEOCACHING_HU_UID'))
    ap.add_argument('--home', default='47.4979,19.0402', help='kiindulópont: lat,lon')
    ap.add_argument('--date', type=date.fromisoformat, default=date.today() + timedelta(days=1))
    ap.add_argument('--depart', help='legkorábbi indulás, HH:MM (alapból napkelte előtt 1 órával)')
    ap.add_argument('--return-by', help='legkésőbbi hazaérés, HH:MM (alapból napnyugta után 1 órával)')
    ap.add_argument('--regions', type=int, default=4, help='ennyi megyét számol újra valós menetidőkkel')
    ap.add_argument('--out', default='geocaching_route.gpx')
    args = ap.parse_args()
    home = tuple(float(x) for x in args.home.split(','))
    sunrise, sunset = sun_times(*home, args.date)
    at = lambda hhmm: datetime.combine(args.date, datetime.strptime(hhmm, '%H:%M').time())
    depart = at(args.depart) if args.depart else sunrise - timedelta(hours=1)
    return_by = at(args.return_by) if args.return_by else sunset + timedelta(hours=1)
    minutes = lambda a, b: (b - a).total_seconds() / 60
    # a ládákat napkelte és napnyugta között keressük, oda- és hazaút lehet sötétben
    fits = lambda out, field, back: (out <= minutes(depart, sunrise) and field <= minutes(sunrise, sunset)
                                     and field + back <= minutes(sunrise, return_by))

    unfound = fetch_unfound(args.uid)
    cands = [dict(c, service=s) for c in unfound if (s := service_min(c)) is not None]
    print(f'{len(unfound)} meg nem talált láda, ebből {len(cands)} jelölt; napkelte {sunrise:%H:%M}, napnyugta {sunset:%H:%M}')

    results = []
    for state, rough in coarse_regions(cands, home, fits, args.regions).items():
        route, home_drive, total, km = refine(cands, rough, home, fits)
        print(f'{state}: {len(route)} láda, {total / 60:.1f} óra, {km:.0f} km')
        results.append((len(route), -total, state, route, home_drive))
    _, _, state, route, home_drive = max(results, key=lambda r: r[:2])

    caches = [(float(c['lat']), float(c['lon'])) for c in unfound]
    points = route_points(route, caches)
    start = sunrise - timedelta(minutes=float(route[0]['drive']))
    write_gpx(args.out, f'{state} {args.date}', home, route, points, start)
    end = start + timedelta(minutes=float(sum(c['drive'] + c['service'] for c in route) + home_drive))
    print(f'\n{state}: indulás {start:%H:%M}, haza {end:%H:%M} -> {args.out}')
    t = start
    for c in route:
        t += timedelta(minutes=float(c['drive']))
        print(f"  {t:%H:%M} {c['waypoint']:8} {c['nickname']}")
        t += timedelta(minutes=float(c['service']))


if __name__ == '__main__':
    main()
