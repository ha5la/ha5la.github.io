import os
import requests
from bs4 import BeautifulSoup
from pathlib import Path

def get_callsign():
    callsign = os.getenv("CALLSIGN")
    return callsign if callsign else os.environ["GITHUB_REPOSITORY_OWNER"]

CALLSIGN = get_callsign()
OUTFILE = Path("wwa-2026-jan.svg")

URL = (
    "https://hamaward.cloud/aw405"
    "?iframe=1&nojs=0&tab=4"
    "&activator_call=WWA"
    "&score=1"
    f"&callsign={CALLSIGN}"
    "&score_name=all_mix"
    "&country=Hungary"
)

HEADERS = {
    "User-Agent": "WWA-badge/1.0"
}


def fetch_stats():
    r = requests.get(URL, headers=HEADERS, timeout=10)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("div", id="resp-table")
    rows = table.find_all("div", class_="resp-table-row")

    header = [
        c.get_text(strip=True)
        for c in rows[0].find_all("div", class_="table-body-cell")
    ]

    data = {
        k: int(v.get_text("|", strip=True).split("|")[0])
        for (k, v) in zip(
            header,
            rows[1].find_all("div", class_="table-body-cell")
        )
    }

    return data["Valid QSO"], data["Score"], data["Rank"]


def generate_svg(qsos, score, rank):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="480" height="44">
  <rect x="0" y="0" width="480" height="44" rx="6" fill="#1e293b"/>
  <rect x="0" y="0" width="120" height="44" rx="6" fill="#334155"/>

  <text x="60" y="28" text-anchor="middle"
        font-family="Arial, Helvetica, sans-serif"
        font-size="13" font-weight="bold" fill="#e5e7eb">
    WWA 2026 Jan
  </text>

  <text x="135" y="28"
        font-family="Arial, Helvetica, sans-serif"
        font-size="14" fill="#e5e7eb">
    {CALLSIGN}
  </text>

  <text x="205" y="28"
        font-family="Arial, Helvetica, sans-serif"
        font-size="14" fill="#cbd5f5">
    QSOs: {qsos}
  </text>

  <text x="295" y="28"
        font-family="Arial, Helvetica, sans-serif"
        font-size="14" fill="#c7d2fe">
    Score: {score}
  </text>

  <text x="390" y="28"
        font-family="Arial, Helvetica, sans-serif"
        font-size="14" fill="#a5b4fc">
    Rank: {rank}
  </text>

  <title>
    WWA 2026 January — {CALLSIGN}
    | QSOs: {qsos}
    | Score: {score}
    | Rank: {rank}
  </title>
</svg>
"""

def main():
    qsos, score, rank = fetch_stats()
    svg = generate_svg(qsos, score, rank)
    OUTFILE.write_text(svg, encoding="utf-8")

if __name__ == "__main__":
    main()
