import requests
import plotly.graph_objects as go
from datetime import datetime, timedelta
from scipy import stats
import numpy as np
from collections import defaultdict
import os
import sys

# ========== BEÁLLÍTÁSOK ==========
# Felhasználók ID-i környezeti változókból
USER_ID_1 = os.environ.get('GEOCACHING_HU_UID')
USER_ID_2 = os.environ.get('GEOCACHING_HU_NEMESIS_UID')

# Ellenőrzés, hogy be vannak-e állítva a környezeti változók
if not USER_ID_1 or not USER_ID_2:
    print("❌ HIBA: Hiányzó környezeti változók!")
    print("\nKérlek állítsd be a következő környezeti változókat:")
    print("  - GEOCACHING_HU_UID (saját geocaching.hu user ID)")
    print("  - GEOCACHING_HU_NEMESIS_UID (vetélytárs geocaching.hu user ID)")
    print("\nPéldák:")
    print("  Linux/Mac: export GEOCACHING_HU_UID=12345")
    print("  Windows:   set GEOCACHING_HU_UID=12345")
    print("  GitHub Actions: secrets.GEOCACHING_HU_UID")
    sys.exit(1)

# Konvertálás integer-re
try:
    USER_ID_1 = int(USER_ID_1)
    USER_ID_2 = int(USER_ID_2)
except ValueError:
    print("❌ HIBA: A környezeti változók értékének számnak kell lennie!")
    sys.exit(1)

USER_NAME_1 = "Jómagam"
USER_NAME_2 = "Vetélytárs"

# Trend számítás beállítása
RECENT_DAYS = 90  # Hány nap adatait használja a trend becsléséhez (30, 60, 90, 180, stb.)

# Kimenet beállítása
OUTPUT_FILE = "geocaching_stats.html"  # Kimeneti fájl neve

# API beállítások
API_URL = "https://api.geocaching.hu/logsbyuser"
# ==================================

def get_user_finds(user_id):
    """
    Lekéri egy felhasználó megtalálásait a geocaching.hu API-ból.
    """
    print(f"Felhasználó {user_id} adatainak lekérése...")

    params = {
        'userid': user_id,
        'logtype': 1,
        'fields': 'date'
    }

    try:
        response = requests.get(API_URL, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()
            print(f"  ✓ Sikeresen lekérve: {len(data)} találat")
            return parse_finds_data(data)
        else:
            print(f"  ✗ Hiba: HTTP {response.status_code}")
            print(f"     {response.text[:200]}")
            return None

    except Exception as e:
        print(f"  ✗ Hiba történt: {e}")
        return None

def parse_finds_data(data):
    """
    Feldolgozza az API válaszát és kinyeri a dátum-találat párokat.
    """
    if not data or not isinstance(data, list):
        return None

    # Találatok csoportosítása dátum szerint
    finds_by_date = defaultdict(int)

    for item in data:
        if 'date' in item:
            date_str = item['date']
            try:
                # Formátum: "2025-10-16 11:12:00"
                date = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                date_only = date.strftime('%Y-%m-%d')
                finds_by_date[date_only] += 1
            except Exception as e:
                print(f"  Figyelmeztetés: Nem sikerült feldolgozni dátumot: {date_str}")
                continue

    if not finds_by_date:
        return None

    # Rendezés és kumulatív számítás
    sorted_dates = sorted(finds_by_date.keys())
    result = []
    total = 0

    for date_str in sorted_dates:
        total += finds_by_date[date_str]
        result.append((date_str, total))

    return result

def convert_to_plot_data(data_list):
    """Dátum stringeket datetime objektummá konvertál."""
    if not data_list:
        return [], []

    dates = [datetime.strptime(d[0], '%Y-%m-%d') for d in data_list]
    counts = [d[1] for d in data_list]
    return dates, counts

def linear_regression(dates, counts, recent_days=90):
    """
    Lineáris regresszió a trendhez, az utolsó N nap adatai alapján.
    Ez pontosabb becslést ad, ha a tempó változott az időben.
    """
    if not dates or len(dates) < 2:
        return 0, 0

    # Csak az utolsó N napot nézzük
    cutoff_date = dates[-1] - timedelta(days=recent_days)
    recent_indices = [i for i, d in enumerate(dates) if d >= cutoff_date]

    if len(recent_indices) < 2:
        # Ha kevés adat van, használjuk az összeset
        recent_indices = list(range(len(dates)))

    recent_dates = [dates[i] for i in recent_indices]
    recent_counts = [counts[i] for i in recent_indices]

    # Regresszió a kiválasztott időszakra
    x = np.array([(d - recent_dates[0]).days for d in recent_dates])
    y = np.array(recent_counts)
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

    # Az intercept-et úgy állítjuk be, hogy illeszkedjen az utolsó ismert ponthoz
    days_from_first = (dates[-1] - dates[0]).days
    adjusted_intercept = counts[-1] - slope * days_from_first

    return slope, adjusted_intercept

def predict_catch_date(dates1, counts1, slope1, intercept1,
                       dates2, counts2, slope2, intercept2):
    """Kiszámolja az utolérési dátumot."""
    if slope1 <= slope2:
        return None, False

    # Jelenlegi különbség
    current_diff = counts2[-1] - counts1[-1]

    if current_diff <= 0:
        # Már utolérted vagy megelőzted
        return None, False

    # Naponta hány találattal csökkenti a különbséget
    daily_gain = slope1 - slope2

    # Hány nap múlva éri utol
    days_to_catch = current_diff / daily_gain

    if days_to_catch < 0:
        return None, False

    catch_date = dates1[-1] + timedelta(days=days_to_catch)
    return catch_date, True

def predict_counts(dates, slope, intercept, base_date, future_dates):
    """Jövőbeli találatok becslése."""
    predictions = []
    for fd in future_dates:
        days = (fd - base_date).days
        predictions.append(max(0, slope * days + intercept))
    return predictions

# ========== ADATOK LEKÉRÉSE ==========
print("=" * 60)
print("GEOCACHING.HU STATISZTIKÁK")
print("=" * 60)
print()

data1 = get_user_finds(USER_ID_1)
data2 = get_user_finds(USER_ID_2)

if data1 is None or data2 is None:
    print("\n❌ Nem sikerült lekérni az adatokat!")
    print("\nEllenőrizd:")
    print("  - A felhasználói ID-k helyesek?")
    print("  - Van internet kapcsolat?")
    print("  - Az API elérhető? (https://api.geocaching.hu)")
    exit(1)

dates1, counts1 = convert_to_plot_data(data1)
dates2, counts2 = convert_to_plot_data(data2)

if not dates1 or not dates2:
    print("\n❌ Nem sikerült feldolgozni az adatokat!")
    exit(1)

# Legutóbbi megtalálás dátuma (ez lesz a "mai" nap)
current_date = max(dates1[-1], dates2[-1])

# ========== TREND SZÁMÍTÁS ==========
slope1, intercept1 = linear_regression(dates1, counts1, RECENT_DAYS)
slope2, intercept2 = linear_regression(dates2, counts2, RECENT_DAYS)

# Jövőbeli predikció (1 év)
future_days = 365
last_date = current_date
future_dates = [last_date + timedelta(days=i) for i in range(0, future_days, 30)]

pred1 = predict_counts(dates1, slope1, intercept1, dates1[0], future_dates)
pred2 = predict_counts(dates2, slope2, intercept2, dates2[0], future_dates)

# Utolérés kiszámítása
catch_date, can_catch = predict_catch_date(
    dates1, counts1, slope1, intercept1,
    dates2, counts2, slope2, intercept2
)

# ========== PLOTLY GRAFIKON ==========
fig = go.Figure()

# Tényleges adatok - Személy 1
fig.add_trace(go.Scatter(
    x=dates1,
    y=counts1,
    mode='lines+markers',
    name=f'{USER_NAME_1} (tényleges)',
    line=dict(color='#2E86AB', width=3),
    marker=dict(size=8, symbol='circle'),
    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Találatok: %{y}<br><extra></extra>'
))

# Tényleges adatok - Személy 2
fig.add_trace(go.Scatter(
    x=dates2,
    y=counts2,
    mode='lines+markers',
    name=f'{USER_NAME_2} (tényleges)',
    line=dict(color='#A23B72', width=3),
    marker=dict(size=8, symbol='square'),
    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Találatok: %{y}<br><extra></extra>'
))

# Jövőbeli becslés - Személy 1
fig.add_trace(go.Scatter(
    x=future_dates,
    y=pred1,
    mode='lines',
    name=f'{USER_NAME_1} (becslés)',
    line=dict(color='#2E86AB', width=2, dash='dash'),
    opacity=0.6,
    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Becsült találatok: %{y:.0f}<br><extra></extra>'
))

# Jövőbeli becslés - Személy 2
fig.add_trace(go.Scatter(
    x=future_dates,
    y=pred2,
    mode='lines',
    name=f'{USER_NAME_2} (becslés)',
    line=dict(color='#A23B72', width=2, dash='dash'),
    opacity=0.6,
    hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Becsült találatok: %{y:.0f}<br><extra></extra>'
))

# Utolérési pont
if can_catch and catch_date < future_dates[-1]:
    catch_count = slope1 * (catch_date - dates1[0]).days + intercept1
    fig.add_trace(go.Scatter(
        x=[catch_date],
        y=[catch_count],
        mode='markers',
        name=f'🎯 Utolérés',
        marker=dict(size=20, color='green', symbol='star', line=dict(color='darkgreen', width=2)),
        hovertemplate=f'<b>Utolérés!</b><br>Dátum: {catch_date.strftime("%Y-%m-%d")}<br>Találatok: {catch_count:.0f}<br><extra></extra>'
    ))

    # Függőleges vonal az utolérési pontnál
    fig.add_vline(x=catch_date, line_dash="dot", line_color="green", opacity=0.5)

# Legutóbbi megtalálás dátuma
#fig.add_vline(
#    x=current_date,
#    line_dash="dash",
#    line_color="red",
#    opacity=0.5,
#    annotation_text=f"Legutóbbi: {current_date.strftime('%Y-%m-%d')}",
#    annotation_position="top"
#)

# Layout beállítások
fig.update_layout(
    title={
        'text': 'Geocaching találatok összehasonlítása (geocaching.hu)',
        'x': 0.5,
        'xanchor': 'center',
        'font': {'size': 20, 'family': 'Arial, sans-serif'}
    },
    xaxis_title='Dátum',
    yaxis_title='Találatok száma',
    hovermode='closest',
    template='plotly_white',
    legend=dict(
        orientation="v",
        yanchor="top",
        y=0.99,
        xanchor="left",
        x=0.01,
        bgcolor="rgba(255, 255, 255, 0.8)",
        bordercolor="gray",
        borderwidth=1
    ),
    height=700,
    font=dict(size=12)
)

# Rács beállítása
fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='lightgray')
fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='lightgray')

# HTML mentése
fig.write_html(OUTPUT_FILE, config={'displayModeBar': True, 'displaylogo': False}, include_plotlyjs='cdn', div_id='geocaching')
print(f"\n✅ Interaktív grafikon mentve: {OUTPUT_FILE}")

# ========== STATISZTIKÁK ==========
print("\n" + "=" * 60)
print("RÉSZLETES STATISZTIKÁK")
print("=" * 60)
print(f"\n⚙️  Trend becslés az utolsó {RECENT_DAYS} nap alapján")

print(f"\n👤 {USER_NAME_1} (ID: {USER_ID_1}):")
print(f"   Jelenlegi találatok: {counts1[-1]}")
print(f"   Első találat: {dates1[0].strftime('%Y-%m-%d')}")
print(f"   Utolsó találat: {dates1[-1].strftime('%Y-%m-%d')}")
print(f"   Aktív napok: {(dates1[-1] - dates1[0]).days} nap")
print(f"   Átlagos tempó: {slope1:.2f} találat/nap")
print(f"                  {slope1*7:.1f} találat/hét")
print(f"                  {slope1*30:.1f} találat/hónap")

print(f"\n👤 {USER_NAME_2} (ID: {USER_ID_2}):")
print(f"   Jelenlegi találatok: {counts2[-1]}")
print(f"   Első találat: {dates2[0].strftime('%Y-%m-%d')}")
print(f"   Utolsó találat: {dates2[-1].strftime('%Y-%m-%d')}")
print(f"   Aktív napok: {(dates2[-1] - dates2[0]).days} nap")
print(f"   Átlagos tempó: {slope2:.2f} találat/nap")
print(f"                  {slope2*7:.1f} találat/hét")
print(f"                  {slope2*30:.1f} találat/hónap")

diff = counts2[-1] - counts1[-1]
if diff > 0:
    print(f"\n📊 Jelenlegi lemaradás: {diff} találat")
    print(f"   Ez {diff/counts2[-1]*100:.1f}%-a a {USER_NAME_2} találatainak")
elif diff < 0:
    print(f"\n🎉 Jelenleg {abs(diff)} találattal vezetsz!")
else:
    print(f"\n🤝 Pontosan ugyanannyi találatotok van!")

if can_catch:
    days_diff = (catch_date - current_date).days
    months_diff = days_diff / 30
    print(f"\n🎯 KIVÁLÓ HÍR! A jelenlegi tempóval utol fogod érni!")
    print(f"   📅 Becsült dátum: {catch_date.strftime('%Y. %B %d.')}")
    print(f"   ⏱️  Időtáv: {days_diff} nap ({months_diff:.1f} hónap)")

    catch_count = int(slope1 * (catch_date - dates1[0]).days + intercept1)
    print(f"   🏆 Akkor várhatóan kb. {catch_count} találatod lesz")

    needed_finds = catch_count - counts1[-1]
    print(f"   📈 Ehhez még {needed_finds} találatra van szükség")

elif counts1[-1] >= counts2[-1]:
    print(f"\n🏆 Gratulálok, már megelőzted a cimborádat!")
else:
    print(f"\n⚠️  A jelenlegi tempóval sajnos nem éred utol.")
    print(f"   A {USER_NAME_2} gyorsabb tempóban gyűjt ({slope2:.2f} vs {slope1:.2f} találat/nap)")

    needed_slope = slope2 + (diff / ((dates1[-1] - dates1[0]).days))
    daily_increase = needed_slope - slope1
    print(f"   Az utoléréshez legalább {needed_slope:.2f} találat/nap kell")
    print(f"   Ez napi {daily_increase:.2f} találattal több a jelenleginél")

print("=" * 60)

print(f"\n✅ Sikeres futás!")
print(f"📊 Interaktív grafikon: {OUTPUT_FILE}")
print(f"📅 Referencia dátum: {current_date.strftime('%Y-%m-%d')} (legutóbbi megtalálás)")
print(f"🖱️  Nyisd meg böngészőben és húzd az egeret az adatpontok fölé!")
print(f"💡 TIP: Használd GitHub Actions-ben napi futáshoz!")
