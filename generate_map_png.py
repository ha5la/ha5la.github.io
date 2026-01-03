#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = ["mercantile","pillow","requests"]
# ///
import requests
import math
import mercantile
import os
from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo
from io import BytesIO
from pathlib import Path

OUT_PNG = "map.png"

TARGET_WIDTH = 1200
TARGET_HEIGHT = 800
MAX_ZOOM = 12
MIN_ZOOM = 4
TILE_SIZE = 256
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MARKER_RADIUS = 4

# ------------------------------------------------------------
# Fetch activation data from SOTL.as
# ------------------------------------------------------------
def get_callsign():
    callsign = os.getenv("CALLSIGN")
    return callsign if callsign else os.environ["GITHUB_REPOSITORY_OWNER"]

url = f'https://sotl.as/api/activations/{get_callsign().upper()}'
data = requests.get(url, timeout=30).json()

points = [
    (
        a["summit"]["coordinates"]["latitude"],
        a["summit"]["coordinates"]["longitude"]
    )
    for a in data
]

if not points:
    raise RuntimeError("No activation coordinates found")

points = sorted(points, key=lambda p: (p[0], p[1]))

lats = [p[0] for p in points]
lons = [p[1] for p in points]

# Add padding around bounds
padding = 0.1
min_lat, max_lat = min(lats) - padding, max(lats) + padding
min_lon, max_lon = min(lons) - padding, max(lons) + padding

def lonlat_to_pixels(lon, lat, zoom):
    """Convert lon/lat to global pixel coordinates"""
    siny = math.sin(lat * math.pi / 180.0)
    siny = min(max(siny, -0.9999), 0.9999)

    scale = 256 * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * scale
    y = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * scale
    return x, y

def choose_zoom(points, padding=0.1):
    for zoom in range(MAX_ZOOM, MIN_ZOOM - 1, -1):
        xs, ys = zip(*(lonlat_to_pixels(lon, lat, zoom) for lat, lon in points))

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        width = max_x - min_x
        height = max_y - min_y

        if width <= TARGET_WIDTH and height <= TARGET_HEIGHT:
            return zoom

    return MIN_ZOOM

ZOOM = choose_zoom(points)
print(f"Using zoom level {ZOOM}")

# ------------------------------------------------------------
# Determine required tiles
# ------------------------------------------------------------
tiles = list(
    mercantile.tiles(
        min_lon, min_lat,
        max_lon, max_lat,
        ZOOM
    )
)

xs = [t.x for t in tiles]
ys = [t.y for t in tiles]

min_x, max_x = min(xs), max(xs)
min_y, max_y = min(ys), max(ys)

width = (max_x - min_x + 1) * TILE_SIZE
height = (max_y - min_y + 1) * TILE_SIZE

img = Image.new("RGB", (width, height))
draw = ImageDraw.Draw(img)

# ------------------------------------------------------------
# Fetch and stitch map tiles
# ------------------------------------------------------------
TILE_CACHE = Path("tile_cache")

def get_tile(z, x, y, session):
    path = TILE_CACHE / str(z) / str(x) / f"{y}.png"
    if path.exists():
        return Image.open(path).convert("RGB")

    path.parent.mkdir(parents=True, exist_ok=True)

    url = TILE_URL.format(z=z, x=x, y=y)
    resp = session.get(url, timeout=20)
    resp.raise_for_status()

    img = Image.open(BytesIO(resp.content))
    img.save(path, format="PNG")

    return img

session = requests.Session()
session.headers["User-Agent"] = "SOTA-map-generator/1.0 (ham radio)"

tiles = sorted(
    tiles,
    key=lambda t: (t.y, t.x)
)

for t in tiles:
    tile = get_tile(t.z, t.x, t.y, session)
    px = (t.x - min_x) * TILE_SIZE
    py = (t.y - min_y) * TILE_SIZE
    img.paste(tile, (px, py))

# ------------------------------------------------------------
# Draw activation markers (FIXED)
# ------------------------------------------------------------
for lat, lon in points:
    gx, gy = lonlat_to_pixels(lon, lat, ZOOM)

    px = int(gx - min_x * TILE_SIZE)
    py = int(gy - min_y * TILE_SIZE)

    draw.ellipse(
        (
            px - MARKER_RADIUS,
            py - MARKER_RADIUS,
            px + MARKER_RADIUS,
            py + MARKER_RADIUS
        ),
        fill="red",
        outline="black"
    )

# ------------------------------------------------------------
# Save result
# ------------------------------------------------------------
raw = img.tobytes()
stable = Image.frombytes("RGB", img.size, raw)
pnginfo = PngInfo()  # EMPTY: no metadata
stable.save(
    OUT_PNG,
    format="PNG",
    pngingo=pnginfo,
    optimize=False,
    compress_level=9,
    add_time=False
)
print(f"Saved {OUT_PNG}")
