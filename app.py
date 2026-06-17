"""
ADS-B Dashboard — Professional Aviation Edition
================================================
Improvements over original:
  • Auto-derives nearest ATC facility & voice frequency from aircraft lat/lon
  • Emergency squawk detection (7500 hijack / 7600 radio / 7700 emergency)
  • Altitude trend arrow from vert_rate
  • Aircraft category icons (A1-A7, B1-B7, C0-C7 etc.)
  • FlightAware deep-link per aircraft
  • Search / filter bar (callsign, hex, squawk)
  • Auto-refresh countdown ring
  • CSV export of logs
  • Better sorting (click headers)
  • RSSI signal bar
  • Professional EFIS-inspired dark theme
  • Units shown (ft, kt, °)
"""

from datetime import datetime
import json
import math
from pathlib import Path

import requests
from flask import Flask, redirect, render_template_string, request, url_for, Response

app = Flask(__name__)

SOURCE_URL = "http://127.0.0.1:8080/data.json"
LOG_PATH = Path("flight_log.txt")
NOTES_PATH = Path("aircraft_notes.json")
STALE_AFTER_SECONDS = 20
OFFLINE_AFTER_SECONDS = 90

# ---------------------------------------------------------------------------
# ATC Frequency database — major centers / approach controls by region
# Format: (lat, lon, name, freq_mhz, type)
# This is a representative set; extend with your local airspace data
# ---------------------------------------------------------------------------
ATC_FACILITIES = [
    # USA Centers (ARTCC)
    (32.90, -97.04, "Fort Worth ARTCC", "132.175", "CTR"),
    (33.94, -118.40, "Los Angeles ARTCC", "135.500", "CTR"),
    (40.63, -73.78, "New York ARTCC", "133.450", "CTR"),
    (41.97, -87.90, "Chicago ARTCC", "133.925", "CTR"),
    (38.94, -77.46, "Washington ARTCC", "134.350", "CTR"),
    (33.63, -84.44, "Atlanta ARTCC", "134.050", "CTR"),
    (29.99, -95.34, "Houston ARTCC", "135.875", "CTR"),
    (39.85, -104.66, "Denver ARTCC", "135.750", "CTR"),
    (37.62, -122.37, "Oakland ARTCC", "132.850", "CTR"),
    (25.79, -80.29, "Miami ARTCC", "132.100", "CTR"),
    (43.11, -76.10, "Boston ARTCC", "133.400", "CTR"),
    (36.08, -86.68, "Memphis ARTCC", "135.625", "CTR"),
    (44.88, -93.22, "Minneapolis ARTCC", "133.825", "CTR"),
    (35.22, -80.94, "Charlotte ARTCC", "133.100", "CTR"),
    (45.59, -122.60, "Seattle ARTCC", "135.025", "CTR"),
    (21.32, -157.92, "Honolulu ARTCC", "132.300", "CTR"),
    # Europe
    (51.14, -0.19, "London Control", "135.575", "CTR"),
    (48.87, 2.35, "Paris Control", "131.325", "CTR"),
    (52.31, 4.76, "Amsterdam Radar", "132.975", "CTR"),
    (52.56, 13.29, "Berlin Control", "136.175", "CTR"),
    (48.35, 11.79, "Munich Radar", "127.950", "CTR"),
    (41.80, 12.24, "Rome Control", "131.200", "CTR"),
    (40.49, -3.56, "Madrid Control", "132.350", "CTR"),
    (59.65, 17.92, "Stockholm Control", "133.700", "CTR"),
    (60.31, 24.96, "Helsinki Radar", "132.525", "CTR"),
    (50.90, 4.48, "Brussels Control", "130.775", "CTR"),
    # Middle East / Asia
    (25.25, 55.36, "Dubai Radar", "124.900", "APP"),
    (24.90, 46.73, "Riyadh Control", "119.050", "CTR"),
    (1.36, 103.99, "Singapore Control", "124.300", "CTR"),
    (35.55, 139.78, "Tokyo Control", "133.000", "CTR"),
    (22.31, 114.17, "Hong Kong Radar", "123.900", "APP"),
    (28.56, 77.10, "Delhi Control", "132.700", "CTR"),
    (19.09, 72.86, "Mumbai Control", "124.550", "CTR"),
    (13.00, 77.58, "Bangalore Radar", "118.000", "APP"),
    # Australia
    (-33.93, 151.17, "Sydney Approach", "123.700", "APP"),
    (-37.67, 144.84, "Melbourne Approach", "132.000", "APP"),
    (-27.38, 153.12, "Brisbane Approach", "124.700", "APP"),
    # Canada
    (43.68, -79.63, "Toronto Control", "133.400", "CTR"),
    (45.47, -73.74, "Montreal Control", "132.850", "CTR"),
    (49.19, -123.18, "Vancouver Control", "135.200", "CTR"),
    # India - more detail for Jamshedpur area
    (22.65, 88.45, "Kolkata Control", "125.100", "CTR"),
    (23.84, 86.42, "Jharkhand Sector", "132.000", "CTR"),
    (23.31, 85.32, "Ranchi Approach", "118.100", "APP"),
]


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km."""
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lon2 - lon1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_atc_frequency(lat, lon):
    """Return (facility_name, frequency_mhz, type, distance_km) for closest ATC station."""
    if lat is None or lon is None:
        return None, None, None, None
    best = None
    best_dist = float("inf")
    for fac_lat, fac_lon, name, freq, ftype in ATC_FACILITIES:
        d = haversine_km(lat, lon, fac_lat, fac_lon)
        if d < best_dist:
            best_dist = d
            best = (name, freq, ftype, round(d))
    return best if best else (None, None, None, None)


# ---------------------------------------------------------------------------
# Emergency squawk detection
# ---------------------------------------------------------------------------
EMERGENCY_SQUAWKS = {
    "7500": ("HIJACK", "red-alert"),
    "7600": ("RADIO FAIL", "amber-alert"),
    "7700": ("EMERGENCY", "red-alert"),
}


def squawk_alert(squawk):
    if squawk and str(squawk) in EMERGENCY_SQUAWKS:
        label, cls = EMERGENCY_SQUAWKS[str(squawk)]
        return label, cls
    return None, None


# ---------------------------------------------------------------------------
# Aircraft category icons / labels
# ---------------------------------------------------------------------------
CATEGORY_LABELS = {
    "A0": "⬜ No info", "A1": "✈ Light", "A2": "✈ Small",
    "A3": "✈ Large", "A4": "✈ High-vortex", "A5": "✈ Heavy",
    "A6": "✈ High-perf", "A7": "🚁 Rotorcraft",
    "B0": "⬜ No info", "B1": "🪂 Glider", "B2": "🎈 LTA",
    "B3": "🪂 Parachute", "B4": "🪁 UAS", "B5": "🚁 Space",
    "B6": "⬜ Surface", "B7": "⬜ Service",
    "C0": "⬜ No info", "C1": "🚗 Ground", "C2": "⬜ Fixed",
}


def category_label(cat):
    if not cat:
        return "-"
    return CATEGORY_LABELS.get(str(cat).upper(), cat)


# ---------------------------------------------------------------------------
# Altitude trend
# ---------------------------------------------------------------------------
def altitude_trend(vert_rate):
    try:
        vr = float(vert_rate)
        if vr > 100:
            return "▲", "trend-up"
        if vr < -100:
            return "▼", "trend-dn"
        return "▬", "trend-lvl"
    except (TypeError, ValueError):
        return "", ""


# ---------------------------------------------------------------------------
# RSSI signal bars (4-bar display)
# ---------------------------------------------------------------------------
def rssi_bars(rssi):
    """Convert dBFS RSSI (typically -50 to -10) to 1-4 bar count."""
    try:
        v = float(rssi)
        if v >= -15:
            return 4
        if v >= -25:
            return 3
        if v >= -35:
            return 2
        return 1
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def load_notes():
    if not NOTES_PATH.exists():
        return {}
    try:
        return json.loads(NOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_notes(notes):
    NOTES_PATH.write_text(json.dumps(notes, indent=2, sort_keys=True), encoding="utf-8")


aircraft_notes = load_notes()

# ---------------------------------------------------------------------------
# In-memory aircraft store
# ---------------------------------------------------------------------------
seen = set()
logged_callsigns = set()
callsigns = {}
aircraft_first_seen = {}
aircraft_store = {}
last_feed_ok = None
last_feed_error = ""


def complete_callsign(value):
    if value is None:
        return None
    raw = str(value)
    clean = raw.strip()
    if not clean:
        return None
    if len(raw) >= 8:
        return clean
    return None


def display_value(value, empty="-"):
    if value is None or value == "":
        return empty
    return value


def parse_number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def aircraft_age_status(last_seen_dt, now):
    age = max(0, int((now - last_seen_dt).total_seconds()))
    if age <= STALE_AFTER_SECONDS:
        return "active", age
    if age <= OFFLINE_AFTER_SECONDS:
        return "stale", age
    return "offline", age


def update_aircraft_store(data):
    now = datetime.now()
    for plane in data:
        hexcode = plane.get("hex", "").strip().upper()
        if not hexcode:
            continue
        if hexcode not in aircraft_first_seen:
            aircraft_first_seen[hexcode] = now
        full_callsign = complete_callsign(plane.get("flight"))
        if full_callsign:
            callsigns[hexcode] = full_callsign
        cached_callsign = callsigns.get(hexcode, "")
        record = aircraft_store.get(hexcode, {})
        record.update(plane)
        record["hex"] = hexcode
        record["display_flight"] = cached_callsign
        record["first_seen_dt"] = aircraft_first_seen[hexcode]
        record["last_seen_dt"] = now
        aircraft_store[hexcode] = record


def dashboard_planes():
    now = datetime.now()
    planes = []
    for hexcode, plane in aircraft_store.items():
        last_seen_dt = plane.get("last_seen_dt", now)
        first_seen_dt = plane.get("first_seen_dt", last_seen_dt)
        age_status, age = aircraft_age_status(last_seen_dt, now)
        note = aircraft_notes.get(hexcode, {})

        # Auto-frequency from position
        lat = plane.get("lat")
        lon = plane.get("lon")
        try:
            lat_f = float(lat) if lat is not None else None
            lon_f = float(lon) if lon is not None else None
        except (ValueError, TypeError):
            lat_f, lon_f = None, None

        atc_name, atc_freq, atc_type, atc_dist = nearest_atc_frequency(lat_f, lon_f)

        # Emergency squawk
        sq_label, sq_cls = squawk_alert(plane.get("squawk"))

        # Altitude trend
        trend_sym, trend_cls = altitude_trend(plane.get("vert_rate"))

        # Bars
        bars = rssi_bars(plane.get("rssi"))

        enriched = dict(plane)
        enriched["age_status"] = age_status
        enriched["row_status"] = f"row-{age_status}"
        enriched["age_sec"] = age
        enriched["age_display"] = f"{age}s"
        enriched["first_seen"] = first_seen_dt.strftime("%H:%M:%S")
        enriched["last_seen"] = last_seen_dt.strftime("%H:%M:%S")
        enriched["altitude_display"] = display_value(plane.get("altitude"))
        enriched["speed_display"] = display_value(plane.get("speed"))
        enriched["track_display"] = display_value(plane.get("track"))
        enriched["lat_display"] = display_value(plane.get("lat"))
        enriched["lon_display"] = display_value(plane.get("lon"))
        enriched["messages_display"] = display_value(plane.get("messages"))
        enriched["vert_rate_display"] = display_value(plane.get("vert_rate"))
        enriched["squawk_display"] = display_value(plane.get("squawk"))
        enriched["category_display"] = category_label(plane.get("category"))
        enriched["rssi_display"] = display_value(plane.get("rssi"))
        enriched["rssi_bars"] = bars
        # Notes (manual override corridor)
        enriched["corridor_display"] = display_value(note.get("corridor"))
        # Auto frequency — show manual override if set, otherwise auto
        if note.get("frequency"):
            enriched["frequency_display"] = note.get("frequency")
            enriched["frequency_source"] = "manual"
        elif atc_freq:
            enriched["frequency_display"] = f"{atc_freq} ({atc_type})"
            enriched["frequency_source"] = "auto"
            enriched["atc_facility"] = atc_name
            enriched["atc_dist_km"] = atc_dist
        else:
            enriched["frequency_display"] = "-"
            enriched["frequency_source"] = "none"
        enriched["altitude_trend"] = trend_sym
        enriched["altitude_trend_cls"] = trend_cls
        enriched["squawk_alert_label"] = sq_label
        enriched["squawk_alert_cls"] = sq_cls
        # FlightAware link
        if enriched.get("display_flight"):
            enriched["fa_link"] = f"https://www.flightaware.com/live/flight/{enriched['display_flight']}"
        elif hexcode:
            enriched["fa_link"] = f"https://www.flightaware.com/live/modes/{hexcode.lower()}/ident/redirect"
        else:
            enriched["fa_link"] = ""
        planes.append(enriched)

    return sorted(
        planes,
        key=lambda p: (
            {"active": 0, "stale": 1, "offline": 2}.get(p["age_status"], 3),
            -parse_number(p.get("messages")),
            p.get("hex", "")
        )
    )


def log_new_aircraft(planes):
    for plane in planes:
        hexcode = plane.get("hex", "")
        if hexcode and hexcode not in seen:
            seen.add(hexcode)
            logline = (
                f"{datetime.now()} | "
                f"{plane.get('display_flight', '')} | "
                f"{hexcode} | "
                f"ALT:{plane.get('altitude', '?')} | "
                f"SPD:{plane.get('speed', '?')} | "
                f"LAT:{plane.get('lat', '?')} | "
                f"LON:{plane.get('lon', '?')}\n"
            )
            print(logline.strip())
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(logline)
        if hexcode and plane.get("display_flight") and hexcode not in logged_callsigns:
            logged_callsigns.add(hexcode)
            logline = (
                f"{datetime.now()} | "
                f"CALLSIGN:{plane.get('display_flight')} | "
                f"{hexcode}\n"
            )
            print(logline.strip())
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(logline)


def read_log_rows(limit=400):
    if not LOG_PATH.exists():
        return []
    rows = []
    for line in LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 3:
            continue
        row = {
            "time": parts[0],
            "callsign": parts[1],
            "hex": parts[2].upper(),
            "altitude": "-", "speed": "-", "lat": "-", "lon": "-",
            "event": "seen"
        }
        if row["callsign"].startswith("CALLSIGN:"):
            row["event"] = "callsign"
            row["callsign"] = row["callsign"].replace("CALLSIGN:", "", 1)
        for part in parts[3:]:
            for prefix, key in [("ALT:", "altitude"), ("SPD:", "speed"),
                                 ("LAT:", "lat"), ("LON:", "lon")]:
                if part.startswith(prefix):
                    row[key] = part.replace(prefix, "", 1)
        note = aircraft_notes.get(row["hex"], {})
        row["corridor"] = display_value(note.get("corridor"))
        row["remarks"] = display_value(note.get("remarks"))
        # Auto-freq for log rows
        try:
            lat_f = float(row["lat"]) if row["lat"] != "-" else None
            lon_f = float(row["lon"]) if row["lon"] != "-" else None
        except ValueError:
            lat_f, lon_f = None, None
        if note.get("frequency"):
            row["frequency"] = note.get("frequency") + " ✎"
        elif lat_f and lon_f:
            _, freq, ftype, dist = nearest_atc_frequency(lat_f, lon_f)
            row["frequency"] = f"{freq} ({ftype}, {dist}km)" if freq else "-"
        else:
            row["frequency"] = "-"
        rows.append(row)
    return rows[-limit:][::-1]


def log_summary(rows):
    unique_hex = {row["hex"] for row in rows if row["hex"]}
    callsign_rows = [row for row in rows if row["event"] == "callsign"]
    corridor_count = sum(1 for h in unique_hex if aircraft_notes.get(h, {}).get("corridor"))
    return {
        "log_count": len(rows),
        "unique_hex": len(unique_hex),
        "callsign_count": len(callsign_rows),
        "corridor_count": corridor_count,
    }


# ---------------------------------------------------------------------------
# Feed helpers
# ---------------------------------------------------------------------------

def refresh_feed():
    global last_feed_error, last_feed_ok
    try:
        response = requests.get(SOURCE_URL, timeout=1.5)
        response.raise_for_status()
        data = response.json()
        update_aircraft_store(data)
        planes = dashboard_planes()
        log_new_aircraft(planes)
        last_feed_ok = datetime.now()
        last_feed_error = ""
    except Exception as e:
        last_feed_error = str(e)


def feed_status_message():
    if last_feed_error:
        if last_feed_ok:
            return "error", (
                f"Receiver offline — displaying last-known traffic from "
                f"{last_feed_ok.strftime('%H:%M:%S')}. {last_feed_error}"
            )
        return "error", (
            f"No receiver feed at {SOURCE_URL}. "
            f"Start dump1090 / readsb and verify the JSON port. {last_feed_error}"
        )
    return "ok", f"Receiver connected  {SOURCE_URL}"


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

:root {
    --bg:       #0b0e13;
    --surface:  #12161c;
    --surface2: #181d25;
    --border:   #232a34;
    --border2:  #2d3748;
    --text:     #e8eaed;
    --muted:    #7a8799;
    --green:    #00d68f;
    --green-dim:#003d28;
    --amber:    #f5c542;
    --amber-dim:#3a2e00;
    --red:      #ff4d4d;
    --red-dim:  #3a0000;
    --blue:     #4da6ff;
    --cyan:     #00c4d4;
    --font:     'Inter', system-ui, sans-serif;
    --mono:     'JetBrains Mono', 'Consolas', monospace;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html { scroll-behavior: smooth; }

body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    font-size: 13px;
    line-height: 1.5;
    min-height: 100vh;
}

a { color: var(--green); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── Layout ── */
.page { padding: 18px 20px; }

.topbar {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 14px;
    margin-bottom: 16px;
}

.brand { display: flex; align-items: center; gap: 12px; }

.brand-icon {
    width: 36px; height: 36px;
    background: linear-gradient(135deg, var(--green) 0%, var(--cyan) 100%);
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
}

h1 {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.3px;
    color: var(--text);
}

.subtitle {
    color: var(--muted);
    font-size: 12px;
    margin-top: 2px;
}

.topright {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 8px;
}

.nav {
    display: flex;
    gap: 4px;
}

.nav a {
    color: var(--muted);
    font-size: 13px;
    font-weight: 500;
    padding: 6px 12px;
    border-radius: 6px;
    border: 1px solid transparent;
    transition: all .15s;
}

.nav a:hover,
.nav a.active {
    color: var(--text);
    border-color: var(--border2);
    background: var(--surface2);
    text-decoration: none;
}

.updated {
    color: var(--muted);
    font-size: 11px;
    display: flex;
    align-items: center;
    gap: 8px;
}

/* ── Stats cards ── */
.stats {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 10px;
    margin-bottom: 14px;
}

.card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
    position: relative;
    overflow: hidden;
}

.card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
}

.card.c-green::before  { background: var(--green); }
.card.c-amber::before  { background: var(--amber); }
.card.c-red::before    { background: var(--red); }
.card.c-blue::before   { background: var(--blue); }
.card.c-cyan::before   { background: var(--cyan); }
.card.c-muted::before  { background: var(--border2); }

.card .label {
    color: var(--muted);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .6px;
}

.card .value {
    font-size: 26px;
    font-weight: 700;
    margin-top: 4px;
    color: var(--text);
    font-variant-numeric: tabular-nums;
}

/* ── Feed bar ── */
.feed {
    border-radius: 8px;
    padding: 9px 14px;
    font-size: 12px;
    font-weight: 500;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.feed::before {
    content: '';
    width: 7px; height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
}

.feed.ok {
    background: var(--green-dim);
    border: 1px solid rgba(0, 214, 143, .3);
    color: var(--green);
}

.feed.ok::before { background: var(--green); box-shadow: 0 0 6px var(--green); }

.feed.error {
    background: var(--amber-dim);
    border: 1px solid rgba(245, 197, 66, .3);
    color: var(--amber);
}

.feed.error::before { background: var(--amber); }

/* ── Toolbar (search + refresh) ── */
.toolbar {
    display: flex;
    gap: 10px;
    align-items: center;
    margin-bottom: 10px;
}

.search-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 7px;
    color: var(--text);
    font-family: var(--mono);
    font-size: 12px;
    padding: 7px 12px;
    width: 240px;
    outline: none;
    transition: border-color .15s;
}

.search-box:focus { border-color: var(--green); }
.search-box::placeholder { color: var(--muted); }

.btn {
    background: var(--surface2);
    border: 1px solid var(--border2);
    border-radius: 7px;
    color: var(--text);
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
    padding: 7px 14px;
    transition: all .15s;
}
.btn:hover { border-color: var(--green); color: var(--green); }

.countdown-ring {
    width: 26px; height: 26px;
    position: relative;
    flex-shrink: 0;
}

.countdown-ring svg { transform: rotate(-90deg); }

.countdown-ring circle {
    fill: none;
    stroke-width: 3;
}

.ring-bg { stroke: var(--border2); }
.ring-fg { stroke: var(--green); stroke-linecap: round; transition: stroke-dashoffset .5s linear; }

.countdown-txt {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 9px;
    font-weight: 700;
    color: var(--muted);
    font-family: var(--mono);
}

.toolsep { flex: 1; }

/* ── Table ── */
.table-wrap {
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: auto;
}

table {
    border-collapse: collapse;
    width: 100%;
    min-width: 1300px;
}

th {
    background: var(--surface);
    color: var(--muted);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: .5px;
    text-transform: uppercase;
    padding: 9px 10px;
    position: sticky;
    top: 0;
    z-index: 2;
    white-space: nowrap;
    border-bottom: 1px solid var(--border2);
    cursor: pointer;
    user-select: none;
}

th:hover { color: var(--text); }
th.sort-asc::after  { content: ' ↑'; color: var(--green); }
th.sort-desc::after { content: ' ↓'; color: var(--green); }

td {
    padding: 8px 10px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
    vertical-align: middle;
}

tr:last-child td { border-bottom: none; }

tr:nth-child(even) td { background: var(--surface); }
tr:nth-child(odd)  td { background: var(--surface2); }

tr:hover td { background: #1e2530 !important; }

.row-stale td  { opacity: .65; }
.row-offline td { opacity: .38; }

/* ── Cell types ── */
.mono { font-family: var(--mono); font-size: 12px; }

.callsign-cell {
    font-family: var(--mono);
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
}

.callsign-cell a { color: var(--text); }
.callsign-cell a:hover { color: var(--green); text-decoration: none; }

.waiting { color: var(--muted); font-style: italic; font-size: 11px; }

.badge {
    display: inline-flex;
    align-items: center;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 700;
    padding: 3px 8px;
    line-height: 1;
    min-width: 60px;
    justify-content: center;
}

.badge-active  { background: rgba(0,214,143,.14); color: var(--green); }
.badge-stale   { background: rgba(245,197,66,.14); color: var(--amber); }
.badge-offline { background: rgba(255,77,77,.12);  color: var(--red); }

.emergency {
    background: var(--red);
    color: #fff;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 800;
    padding: 2px 6px;
    letter-spacing: .5px;
    animation: pulse-red 1s infinite;
    margin-left: 4px;
}

@keyframes pulse-red {
    0%, 100% { opacity: 1; }
    50%       { opacity: .5; }
}

.trend-up  { color: var(--green); font-size: 12px; }
.trend-dn  { color: var(--red);   font-size: 12px; }
.trend-lvl { color: var(--muted); font-size: 12px; }

.freq-auto   { color: var(--cyan);  font-size: 11px; }
.freq-manual { color: var(--amber); font-size: 11px; }
.freq-none   { color: var(--muted); }

.atc-tip { color: var(--muted); font-size: 10px; display: block; margin-top: 1px; }

.signal-bars {
    display: inline-flex;
    align-items: flex-end;
    gap: 2px;
    height: 14px;
}

.signal-bars span {
    width: 3px;
    background: var(--border2);
    border-radius: 1px;
    display: block;
}

.signal-bars span.lit { background: var(--green); }
.signal-bars .b1 { height: 4px; }
.signal-bars .b2 { height: 7px; }
.signal-bars .b3 { height: 10px; }
.signal-bars .b4 { height: 14px; }

.fa-link {
    font-size: 10px;
    color: var(--muted);
}
.fa-link:hover { color: var(--blue); }

/* ── Log page ── */
.note-form {
    display: grid;
    grid-template-columns: 90px 110px 1fr auto;
    gap: 5px;
    min-width: 400px;
}

.note-form input {
    background: #0d1117;
    border: 1px solid var(--border);
    border-radius: 5px;
    color: var(--text);
    font-size: 12px;
    padding: 5px 7px;
    font-family: var(--font);
    outline: none;
    transition: border-color .15s;
}

.note-form input:focus { border-color: var(--green); }
.note-form input[readonly] { color: var(--muted); }

.note-form button {
    background: var(--green);
    border: 0;
    border-radius: 5px;
    color: #021a0e;
    cursor: pointer;
    font-size: 11px;
    font-weight: 700;
    padding: 5px 10px;
}

.note-form button:hover { opacity: .85; }

.event-seen     { background: rgba(0,214,143,.12); color: var(--green); }
.event-callsign { background: rgba(77,166,255,.12); color: var(--blue); }

/* ── Empty state ── */
.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: var(--muted);
}

.empty-state .icon { font-size: 40px; margin-bottom: 12px; }
.empty-state h2 { color: var(--text); font-size: 16px; margin-bottom: 6px; }

/* ── Responsive ── */
@media (max-width: 900px) {
    .stats { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 600px) {
    .page { padding: 12px; }
    .topbar { flex-direction: column; align-items: flex-start; }
    .stats { grid-template-columns: repeat(2, 1fr); }
}
</style>
"""

# ---------------------------------------------------------------------------
# Signal bar macro
# ---------------------------------------------------------------------------
def render_signal_bars(bars):
    html = '<span class="signal-bars">'
    for i, cls in enumerate(["b1", "b2", "b3", "b4"], 1):
        lit = "lit" if i <= bars else ""
        html += f'<span class="{cls} {lit}"></span>'
    html += "</span>"
    return html


# ---------------------------------------------------------------------------
# HTML Templates
# ---------------------------------------------------------------------------

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>ADS-B Control — Live Traffic</title>
    {{ css|safe }}
</head>
<body>

<div class="page">
<!-- Topbar -->
<div class="topbar">
    <div class="brand">
        <div class="brand-icon">✈</div>
        <div>
            <h1>ADS-B Control</h1>
            <div class="subtitle">Live airspace surveillance &mdash; {{ updated_at }} UTC</div>
        </div>
    </div>
    <div class="topright">
        <nav class="nav">
            <a href="/" class="active">Live Traffic</a>
            <a href="/logs">Log Analysis</a>
        </nav>
    </div>
</div>

<!-- Stats -->
<div class="stats">
    <div class="card c-green">
        <div class="label">Active</div>
        <div class="value">{{ active_count }}</div>
    </div>
    <div class="card c-amber">
        <div class="label">Stale (&gt;{{ stale_s }}s)</div>
        <div class="value">{{ stale_count }}</div>
    </div>
    <div class="card c-red">
        <div class="label">Offline</div>
        <div class="value">{{ offline_count }}</div>
    </div>
    <div class="card c-cyan">
        <div class="label">Callsigns</div>
        <div class="value">{{ known_callsigns }}</div>
    </div>
    <div class="card c-muted">
        <div class="label">Total Tracks</div>
        <div class="value">{{ total_count }}</div>
    </div>
    <div class="card c-red">
        <div class="label">Emergencies</div>
        <div class="value">{{ emergency_count }}</div>
    </div>
</div>

<!-- Feed status -->
<div class="feed {{ feed_class }}">{{ feed_status }}</div>

<!-- Toolbar -->
<div class="toolbar">
    <input class="search-box" id="search" type="text" placeholder="Filter callsign / hex / squawk…" oninput="filterTable()">
    <a class="btn" href="/export/csv" download="adsb_log.csv">⬇ Export CSV</a>
    <span class="toolsep"></span>
    <div class="countdown-ring" title="Auto-refresh in Ns">
        <svg viewBox="0 0 26 26" width="26" height="26">
            <circle class="ring-bg" cx="13" cy="13" r="10"/>
            <circle class="ring-fg" id="ring" cx="13" cy="13" r="10"
                    stroke-dasharray="62.83"
                    stroke-dashoffset="0"/>
        </svg>
        <div class="countdown-txt" id="ring-txt">5</div>
    </div>
</div>

<!-- Table -->
<div class="table-wrap">
<table id="main-table">
<thead>
<tr>
    <th onclick="sortTable(0)">Callsign</th>
    <th onclick="sortTable(1)">Status</th>
    <th onclick="sortTable(2)">HEX</th>
    <th onclick="sortTable(3)">Squawk</th>
    <th onclick="sortTable(4)">Category</th>
    <th onclick="sortTable(5)">Altitude (ft)</th>
    <th>Trend</th>
    <th onclick="sortTable(7)">V/S (fpm)</th>
    <th onclick="sortTable(8)">Speed (kt)</th>
    <th onclick="sortTable(9)">Track (°)</th>
    <th onclick="sortTable(10)">Latitude</th>
    <th onclick="sortTable(11)">Longitude</th>
    <th>RSSI</th>
    <th onclick="sortTable(13)">Messages</th>
    <th>ATC Frequency</th>
    <th>Corridor</th>
    <th>First Seen</th>
    <th>Last Seen</th>
    <th>Age</th>
</tr>
</thead>
<tbody id="table-body">
{% if not planes %}
<tr><td colspan="19">
    <div class="empty-state">
        <div class="icon">📡</div>
        <h2>No aircraft in range</h2>
        <p>Waiting for ADS-B receiver data from {{ source_url }}</p>
    </div>
</td></tr>
{% endif %}
{% for p in planes %}
<tr class="{{ p.row_status }}"
    data-search="{{ (p.display_flight or '') | lower }} {{ p.hex | lower }} {{ p.squawk_display | lower }}">
    <td class="callsign-cell">
        {% if p.display_flight %}
            <a href="{{ p.fa_link }}" target="_blank" rel="noopener" title="View on FlightAware">{{ p.display_flight }}</a>
        {% else %}
            <span class="waiting">acquiring…</span>
        {% endif %}
        {% if p.squawk_alert_label %}
            <span class="emergency">{{ p.squawk_alert_label }}</span>
        {% endif %}
    </td>
    <td><span class="badge badge-{{ p.age_status }}">{{ p.age_status }}</span></td>
    <td class="mono">
        <a class="fa-link" href="{{ p.fa_link }}" target="_blank" rel="noopener" title="FlightAware">{{ p.hex }}</a>
    </td>
    <td class="mono {% if p.squawk_alert_cls %}{{ p.squawk_alert_cls }}{% endif %}">{{ p.squawk_display }}</td>
    <td>{{ p.category_display }}</td>
    <td class="mono">{{ p.altitude_display }}</td>
    <td class="{{ p.altitude_trend_cls }}">{{ p.altitude_trend }}</td>
    <td class="mono">{{ p.vert_rate_display }}</td>
    <td class="mono">{{ p.speed_display }}</td>
    <td class="mono">{{ p.track_display }}</td>
    <td class="mono">{{ p.lat_display }}</td>
    <td class="mono">{{ p.lon_display }}</td>
    <td>{{ p.signal_bars_html|safe }} <span class="mono" style="font-size:10px;color:var(--muted);">{{ p.rssi_display }}</span></td>
    <td class="mono">{{ p.messages_display }}</td>
    <td>
        {% if p.frequency_source == 'auto' %}
            <span class="freq-auto">{{ p.frequency_display }}</span>
            <span class="atc-tip">{{ p.atc_facility }} · {{ p.atc_dist_km }}km</span>
        {% elif p.frequency_source == 'manual' %}
            <span class="freq-manual">{{ p.frequency_display }} ✎</span>
        {% else %}
            <span class="freq-none">—</span>
        {% endif %}
    </td>
    <td>{{ p.corridor_display }}</td>
    <td class="mono" style="font-size:11px;">{{ p.first_seen }}</td>
    <td class="mono" style="font-size:11px;">{{ p.last_seen }}</td>
    <td class="mono" style="font-size:11px;color:var(--muted);">{{ p.age_display }}</td>
</tr>
{% endfor %}
</tbody>
</table>
</div>
</div><!-- /page -->

<script>
/* ── Auto-refresh countdown ── */
const INTERVAL = 5;
let remaining = INTERVAL;
const ring = document.getElementById('ring');
const txt  = document.getElementById('ring-txt');
const circ = 2 * Math.PI * 10; // r=10

function tick() {
    remaining--;
    const pct = remaining / INTERVAL;
    ring.style.strokeDashoffset = circ * (1 - pct);
    txt.textContent = remaining;
    if (remaining <= 0) location.reload();
    else setTimeout(tick, 1000);
}
setTimeout(tick, 1000);

/* ── Search / filter ── */
function filterTable() {
    const q = document.getElementById('search').value.toLowerCase();
    document.querySelectorAll('#table-body tr[data-search]').forEach(row => {
        row.style.display = row.dataset.search.includes(q) ? '' : 'none';
    });
}

/* ── Column sort ── */
let sortCol = -1, sortDir = 1;
function sortTable(col) {
    const tbody = document.getElementById('table-body');
    const rows  = Array.from(tbody.querySelectorAll('tr[data-search]'));
    if (sortCol === col) sortDir *= -1;
    else { sortCol = col; sortDir = 1; }
    rows.sort((a, b) => {
        const va = a.cells[col]?.textContent.trim() || '';
        const vb = b.cells[col]?.textContent.trim() || '';
        const na = parseFloat(va), nb = parseFloat(vb);
        if (!isNaN(na) && !isNaN(nb)) return (na - nb) * sortDir;
        return va.localeCompare(vb) * sortDir;
    });
    rows.forEach(r => tbody.appendChild(r));
    document.querySelectorAll('th').forEach((th, i) => {
        th.classList.remove('sort-asc','sort-desc');
        if (i === col) th.classList.add(sortDir === 1 ? 'sort-asc' : 'sort-desc');
    });
}
</script>
</body>
</html>
"""

LOGS_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>ADS-B Control — Log Analysis</title>
    {{ css|safe }}
</head>
<body>

<div class="page">
<div class="topbar">
    <div class="brand">
        <div class="brand-icon">📋</div>
        <div>
            <h1>Log Analysis</h1>
            <div class="subtitle">Annotate aircraft with corridor tags and remarks. Auto-frequency shown where available.</div>
        </div>
    </div>
    <nav class="nav">
        <a href="/">Live Traffic</a>
        <a href="/logs" class="active">Log Analysis</a>
    </nav>
</div>

<div class="stats">
    <div class="card c-muted"><div class="label">Log Rows</div><div class="value">{{ summary.log_count }}</div></div>
    <div class="card c-cyan"><div class="label">Unique Tracks</div><div class="value">{{ summary.unique_hex }}</div></div>
    <div class="card c-blue"><div class="label">Callsign Events</div><div class="value">{{ summary.callsign_count }}</div></div>
    <div class="card c-green"><div class="label">Corridors Tagged</div><div class="value">{{ summary.corridor_count }}</div></div>
</div>

<div class="toolbar">
    <input class="search-box" id="search" type="text" placeholder="Filter callsign / hex…" oninput="filterLog()">
    <a class="btn" href="/export/csv" download="adsb_log.csv">⬇ Export CSV</a>
</div>

<div class="table-wrap">
<table>
<thead>
<tr>
    <th>Annotate</th>
    <th>Time</th>
    <th>Event</th>
    <th>Callsign</th>
    <th>HEX</th>
    <th>Altitude (ft)</th>
    <th>Speed (kt)</th>
    <th>Lat</th>
    <th>Lon</th>
    <th>ATC Frequency</th>
    <th>Corridor</th>
    <th>Remarks</th>
</tr>
</thead>
<tbody id="log-body">
{% for row in rows %}
<tr data-search="{{ row.callsign | lower }} {{ row.hex | lower }}">
    <td>
        <form class="note-form" method="post" action="/notes">
            <input name="hex" value="{{ row.hex }}" readonly title="ICAO hex">
            <input name="corridor" value="{{ '' if row.corridor == '-' else row.corridor }}" placeholder="Corridor / Route">
            <input name="remarks" value="{{ '' if row.remarks == '-' else row.remarks }}" placeholder="Remarks">
            <button type="submit">Save</button>
        </form>
    </td>
    <td class="mono" style="font-size:11px;">{{ row.time }}</td>
    <td><span class="badge event-{{ row.event }}">{{ row.event }}</span></td>
    <td class="mono">{{ row.callsign }}</td>
    <td class="mono">{{ row.hex }}</td>
    <td class="mono">{{ row.altitude }}</td>
    <td class="mono">{{ row.speed }}</td>
    <td class="mono">{{ row.lat }}</td>
    <td class="mono">{{ row.lon }}</td>
    <td class="freq-auto" style="font-size:11px;">{{ row.frequency }}</td>
    <td>{{ row.corridor }}</td>
    <td style="color:var(--muted);font-size:11px;">{{ row.remarks }}</td>
</tr>
{% endfor %}
{% if not rows %}
<tr><td colspan="12">
    <div class="empty-state">
        <div class="icon">📂</div>
        <h2>No log entries yet</h2>
        <p>Aircraft seen on the live dashboard will appear here.</p>
    </div>
</td></tr>
{% endif %}
</tbody>
</table>
</div>
</div>

<script>
function filterLog() {
    const q = document.getElementById('search').value.toLowerCase();
    document.querySelectorAll('#log-body tr[data-search]').forEach(r => {
        r.style.display = r.dataset.search.includes(q) ? '' : 'none';
    });
}
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    refresh_feed()
    planes = dashboard_planes()
    for p in planes:
        p["signal_bars_html"] = render_signal_bars(p["rssi_bars"])
    feed_class, feed_status = feed_status_message()
    return render_template_string(
        DASHBOARD_HTML,
        css=BASE_CSS,
        planes=planes,
        active_count=sum(1 for p in planes if p["age_status"] == "active"),
        stale_count=sum(1 for p in planes if p["age_status"] == "stale"),
        offline_count=sum(1 for p in planes if p["age_status"] == "offline"),
        total_count=len(planes),
        known_callsigns=sum(1 for p in planes if p.get("display_flight")),
        emergency_count=sum(1 for p in planes if p.get("squawk_alert_label")),
        stale_s=STALE_AFTER_SECONDS,
        updated_at=datetime.utcnow().strftime("%H:%M:%S"),
        feed_status=feed_status,
        feed_class=feed_class,
        source_url=SOURCE_URL,
    )


@app.route("/logs")
def logs():
    rows = read_log_rows()
    return render_template_string(
        LOGS_HTML,
        css=BASE_CSS,
        rows=rows,
        summary=log_summary(rows),
    )


@app.route("/notes", methods=["POST"])
def update_notes():
    hexcode = request.form.get("hex", "").strip().upper()
    if hexcode:
        existing = aircraft_notes.get(hexcode, {})
        existing["corridor"] = request.form.get("corridor", "").strip()
        existing["remarks"] = request.form.get("remarks", "").strip()
        # Keep manual frequency override if supplied (blank = fall back to auto)
        freq = request.form.get("frequency", "").strip()
        if freq:
            existing["frequency"] = freq
        else:
            existing.pop("frequency", None)
        aircraft_notes[hexcode] = existing
        save_notes(aircraft_notes)
    return redirect(url_for("logs"))


@app.route("/export/csv")
def export_csv():
    """Download flight log as CSV."""
    rows = read_log_rows(limit=10000)
    lines = ["time,event,callsign,hex,altitude_ft,speed_kt,lat,lon,corridor,frequency,remarks"]
    for r in rows:
        def esc(v):
            return f'"{str(v).replace(chr(34), chr(39))}"'
        lines.append(",".join(esc(r.get(k, "")) for k in
            ["time","event","callsign","hex","altitude","speed","lat","lon",
             "corridor","frequency","remarks"]))
    return Response(
        "\n".join(lines),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=adsb_log.csv"}
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)