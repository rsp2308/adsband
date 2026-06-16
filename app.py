from datetime import datetime
import json
from pathlib import Path

import requests
from flask import Flask, redirect, render_template_string, request, url_for

app = Flask(__name__)

SOURCE_URL = "http://127.0.0.1:8080/data.json"
LOG_PATH = Path("flight_log.txt")
NOTES_PATH = Path("aircraft_notes.json")
STALE_AFTER_SECONDS = 20
OFFLINE_AFTER_SECONDS = 90

seen = set()
logged_callsigns = set()
callsigns = {}
aircraft_first_seen = {}
aircraft_store = {}
last_feed_ok = None
last_feed_error = ""


def load_notes():
    if not NOTES_PATH.exists():
        return {}

    try:
        return json.loads(NOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_notes(notes):
    NOTES_PATH.write_text(
        json.dumps(notes, indent=2, sort_keys=True),
        encoding="utf-8"
    )


aircraft_notes = load_notes()


def complete_callsign(value):
    """Return a stripped callsign only after the full 8-char ADS-B field arrives."""
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


def aircraft_age_status(last_seen, now):
    age = max(0, int((now - last_seen).total_seconds()))
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
        record["callsign_status"] = "confirmed" if cached_callsign else "receiving"
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

        enriched = dict(plane)
        enriched["age_status"] = age_status
        enriched["row_status"] = f"row-{age_status}"
        enriched["age_display"] = f"{age}s"
        enriched["first_seen"] = first_seen_dt.strftime("%H:%M:%S")
        enriched["last_seen"] = last_seen_dt.strftime("%H:%M:%S")
        enriched["altitude_display"] = display_value(plane.get("altitude"))
        enriched["speed_display"] = display_value(plane.get("speed"))
        enriched["track_display"] = display_value(plane.get("track"))
        enriched["lat_display"] = display_value(plane.get("lat"))
        enriched["lon_display"] = display_value(plane.get("lon"))
        enriched["messages_display"] = display_value(plane.get("messages"))
        enriched["seen_display"] = display_value(plane.get("seen"))
        enriched["seen_pos_display"] = display_value(plane.get("seen_pos"))
        enriched["vert_rate_display"] = display_value(plane.get("vert_rate"))
        enriched["squawk_display"] = display_value(plane.get("squawk"))
        enriched["category_display"] = display_value(plane.get("category"))
        enriched["rssi_display"] = display_value(plane.get("rssi"))
        enriched["corridor_display"] = display_value(note.get("corridor"))
        enriched["frequency_display"] = display_value(note.get("frequency"))
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
            "altitude": "-",
            "speed": "-",
            "lat": "-",
            "lon": "-",
            "event": "seen"
        }

        if row["callsign"].startswith("CALLSIGN:"):
            row["event"] = "callsign"
            row["callsign"] = row["callsign"].replace("CALLSIGN:", "", 1)

        for part in parts[3:]:
            if part.startswith("ALT:"):
                row["altitude"] = part.replace("ALT:", "", 1)
            elif part.startswith("SPD:"):
                row["speed"] = part.replace("SPD:", "", 1)
            elif part.startswith("LAT:"):
                row["lat"] = part.replace("LAT:", "", 1)
            elif part.startswith("LON:"):
                row["lon"] = part.replace("LON:", "", 1)

        note = aircraft_notes.get(row["hex"], {})
        row["corridor"] = display_value(note.get("corridor"))
        row["frequency"] = display_value(note.get("frequency"))
        row["remarks"] = display_value(note.get("remarks"))
        rows.append(row)

    return rows[-limit:][::-1]


def log_summary(rows):
    unique_hex = {row["hex"] for row in rows if row["hex"]}
    callsign_rows = [row for row in rows if row["event"] == "callsign"]
    corridor_count = sum(
        1 for hexcode in unique_hex
        if aircraft_notes.get(hexcode, {}).get("corridor")
    )
    frequency_count = sum(
        1 for hexcode in unique_hex
        if aircraft_notes.get(hexcode, {}).get("frequency")
    )
    return {
        "log_count": len(rows),
        "unique_hex": len(unique_hex),
        "callsign_count": len(callsign_rows),
        "corridor_count": corridor_count,
        "frequency_count": frequency_count
    }


BASE_CSS = """
    <style>
        :root{
            color-scheme:dark;
            --bg:#121212;
            --panel:#1b1d1f;
            --panel-2:#232629;
            --line:#34383d;
            --text:#f3f4f1;
            --muted:#aeb4af;
            --green:#5ee08f;
            --amber:#f3be5c;
            --red:#ff7a7a;
        }

        *{ box-sizing:border-box; }

        body{
            background:var(--bg);
            color:var(--text);
            font-family:Arial,sans-serif;
            margin:0;
        }

        a{
            color:var(--green);
            text-decoration:none;
        }

        .page{ padding:20px; }

        .topbar{
            align-items:flex-end;
            border-bottom:1px solid var(--line);
            display:flex;
            gap:16px;
            justify-content:space-between;
            margin-bottom:16px;
            padding-bottom:14px;
        }

        h1{
            color:var(--green);
            font-size:28px;
            line-height:1.1;
            margin:0;
        }

        .nav{
            display:flex;
            gap:14px;
            justify-content:flex-end;
            margin-top:8px;
        }

        .subtle{
            color:var(--muted);
            font-size:13px;
            margin-top:6px;
        }

        .stats{
            display:grid;
            gap:10px;
            grid-template-columns:repeat(5,minmax(120px,1fr));
            margin-bottom:16px;
        }

        .card{
            background:var(--panel);
            border:1px solid var(--line);
            border-radius:8px;
            padding:12px;
        }

        .label{
            color:var(--muted);
            font-size:12px;
            text-transform:uppercase;
        }

        .value{
            font-size:24px;
            font-weight:700;
            margin-top:4px;
        }

        .feed{
            border:1px solid var(--line);
            border-radius:8px;
            margin-bottom:16px;
            padding:10px 12px;
        }

        .feed.ok{
            background:rgba(94,224,143,.12);
            color:var(--green);
        }

        .feed.error{
            background:rgba(243,190,92,.12);
            color:var(--amber);
        }

        .table-wrap{
            border:1px solid var(--line);
            border-radius:8px;
            overflow:auto;
        }

        table{
            border-collapse:collapse;
            min-width:1180px;
            width:100%;
        }

        th{
            background:#262a2d;
            color:#dce2dd;
            font-size:12px;
            position:sticky;
            text-transform:uppercase;
            top:0;
            z-index:1;
        }

        td,th{
            border-bottom:1px solid var(--line);
            padding:9px 8px;
            text-align:left;
            white-space:nowrap;
        }

        tr:nth-child(even){ background:var(--panel); }
        tr:nth-child(odd){ background:var(--panel-2); }
        tr:hover{ background:#30353a; }

        .row-stale{
            color:#c3c5c0;
            opacity:.65;
        }

        .row-offline{
            color:#9b9d99;
            opacity:.42;
        }

        .mono{ font-family:Consolas,Monaco,monospace; }

        .status{
            border-radius:999px;
            display:inline-block;
            font-size:12px;
            font-weight:700;
            min-width:78px;
            padding:4px 8px;
            text-align:center;
        }

        .confirmed,.active{
            background:rgba(94,224,143,.16);
            color:var(--green);
        }

        .receiving,.stale{
            background:rgba(243,190,92,.16);
            color:var(--amber);
        }

        .offline{
            background:rgba(255,122,122,.14);
            color:var(--red);
        }

        .empty{ color:var(--muted); }

        form.note-form{
            display:grid;
            gap:6px;
            grid-template-columns:110px 120px 150px 1fr auto;
            min-width:620px;
        }

        input{
            background:#101214;
            border:1px solid var(--line);
            border-radius:6px;
            color:var(--text);
            padding:7px 8px;
        }

        button{
            background:var(--green);
            border:0;
            border-radius:6px;
            color:#07120a;
            cursor:pointer;
            font-weight:700;
            padding:7px 10px;
        }

        @media (max-width:760px){
            .page{ padding:14px; }
            .topbar{
                align-items:flex-start;
                flex-direction:column;
            }
            .stats{
                grid-template-columns:repeat(2,minmax(120px,1fr));
            }
        }
    </style>
"""


DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>ADS-B Dashboard</title>
    <meta http-equiv="refresh" content="5">
    {{ css|safe }}
</head>
<body>

<div class="page">
<div class="topbar">
    <div>
        <h1>ADS-B Dashboard</h1>
        <div class="subtle">Callsigns update after complete aircraft ID packets. Missing aircraft stay visible as stale/offline.</div>
    </div>
    <div>
        <div class="nav"><a href="/">Dashboard</a><a href="/logs">Logs</a></div>
        <div class="subtle">Updated {{ updated_at }}</div>
    </div>
</div>

<div class="stats">
    <div class="card"><div class="label">Active</div><div class="value">{{ active_count }}</div></div>
    <div class="card"><div class="label">Stale</div><div class="value">{{ stale_count }}</div></div>
    <div class="card"><div class="label">Offline</div><div class="value">{{ offline_count }}</div></div>
    <div class="card"><div class="label">Known Callsigns</div><div class="value">{{ known_callsigns }}</div></div>
    <div class="card"><div class="label">Total Hex</div><div class="value">{{ total_count }}</div></div>
</div>

<div class="feed {{ feed_class }}">{{ feed_status }}</div>

<div class="table-wrap">
<table>
<tr>
<th>Callsign</th>
<th>Age</th>
<th>Status</th>
<th>HEX</th>
<th>Corridor</th>
<th>Voice Freq</th>
<th>Category</th>
<th>Altitude</th>
<th>Vertical Rate</th>
<th>Speed</th>
<th>Track</th>
<th>Latitude</th>
<th>Longitude</th>
<th>Squawk</th>
<th>RSSI</th>
<th>Messages</th>
<th>First Seen</th>
<th>Last Seen</th>
</tr>

{% for p in planes %}
<tr class="{{ p.row_status }}">
<td class="mono">{% if p.display_flight %}{{ p.display_flight }}{% else %}<span class="empty">waiting</span>{% endif %}</td>
<td>{{ p.age_display }}</td>
<td><span class="status {{ p.age_status }}">{{ p.age_status }}</span></td>
<td class="mono">{{ p.hex }}</td>
<td>{{ p.corridor_display }}</td>
<td>{{ p.frequency_display }}</td>
<td>{{ p.category_display }}</td>
<td>{{ p.altitude_display }}</td>
<td>{{ p.vert_rate_display }}</td>
<td>{{ p.speed_display }}</td>
<td>{{ p.track_display }}</td>
<td class="mono">{{ p.lat_display }}</td>
<td class="mono">{{ p.lon_display }}</td>
<td class="mono">{{ p.squawk_display }}</td>
<td>{{ p.rssi_display }}</td>
<td>{{ p.messages_display }}</td>
<td>{{ p.first_seen }}</td>
<td>{{ p.last_seen }}</td>
</tr>
{% endfor %}

</table>
</div>
</div>

</body>
</html>
"""


LOGS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>ADS-B Logs</title>
    {{ css|safe }}
</head>
<body>

<div class="page">
<div class="topbar">
    <div>
        <h1>ADS-B Log Analysis</h1>
        <div class="subtle">Add corridor, voice frequency, and remarks by HEX. These notes show on the live dashboard too.</div>
    </div>
    <div class="nav"><a href="/">Dashboard</a><a href="/logs">Logs</a></div>
</div>

<div class="stats">
    <div class="card"><div class="label">Log Rows</div><div class="value">{{ summary.log_count }}</div></div>
    <div class="card"><div class="label">Unique Hex</div><div class="value">{{ summary.unique_hex }}</div></div>
    <div class="card"><div class="label">Callsign Updates</div><div class="value">{{ summary.callsign_count }}</div></div>
    <div class="card"><div class="label">Corridors Named</div><div class="value">{{ summary.corridor_count }}</div></div>
    <div class="card"><div class="label">Frequencies</div><div class="value">{{ summary.frequency_count }}</div></div>
</div>

<div class="table-wrap">
<table>
<tr>
<th>Notes</th>
<th>Time</th>
<th>Event</th>
<th>Callsign</th>
<th>HEX</th>
<th>Altitude</th>
<th>Speed</th>
<th>Lat</th>
<th>Lon</th>
<th>Corridor</th>
<th>Voice Freq</th>
<th>Remarks</th>
</tr>

{% for row in rows %}
<tr>
<td>
    <form class="note-form" method="post" action="/notes">
        <input name="hex" value="{{ row.hex }}" readonly>
        <input name="corridor" value="{{ '' if row.corridor == '-' else row.corridor }}" placeholder="Corridor">
        <input name="frequency" value="{{ '' if row.frequency == '-' else row.frequency }}" placeholder="Voice freq">
        <input name="remarks" value="{{ '' if row.remarks == '-' else row.remarks }}" placeholder="Remarks">
        <button type="submit">Save</button>
    </form>
</td>
<td>{{ row.time }}</td>
<td><span class="status {{ 'confirmed' if row.event == 'callsign' else 'active' }}">{{ row.event }}</span></td>
<td class="mono">{{ row.callsign }}</td>
<td class="mono">{{ row.hex }}</td>
<td>{{ row.altitude }}</td>
<td>{{ row.speed }}</td>
<td class="mono">{{ row.lat }}</td>
<td class="mono">{{ row.lon }}</td>
<td>{{ row.corridor }}</td>
<td>{{ row.frequency }}</td>
<td>{{ row.remarks }}</td>
</tr>
{% endfor %}

</table>
</div>
</div>

</body>
</html>
"""


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
            return (
                "error",
                f"Receiver feed is not responding. Keeping aircraft on screen from "
                f"{last_feed_ok.strftime('%H:%M:%S')}. Error: {last_feed_error}"
            )
        return (
            "error",
            f"Receiver feed is not responding at {SOURCE_URL}. "
            f"Start dump1090/readsb or check the data.json port. Error: {last_feed_error}"
        )

    return "ok", f"Receiver feed connected: {SOURCE_URL}"


@app.route("/")
def home():
    refresh_feed()
    planes = dashboard_planes()
    feed_class, feed_status = feed_status_message()

    return render_template_string(
        DASHBOARD_HTML,
        css=BASE_CSS,
        planes=planes,
        active_count=sum(1 for plane in planes if plane["age_status"] == "active"),
        stale_count=sum(1 for plane in planes if plane["age_status"] == "stale"),
        offline_count=sum(1 for plane in planes if plane["age_status"] == "offline"),
        total_count=len(planes),
        known_callsigns=sum(1 for plane in planes if plane.get("display_flight")),
        updated_at=datetime.now().strftime("%H:%M:%S"),
        feed_status=feed_status,
        feed_class=feed_class
    )


@app.route("/logs")
def logs():
    rows = read_log_rows()
    return render_template_string(
        LOGS_HTML,
        css=BASE_CSS,
        rows=rows,
        summary=log_summary(rows)
    )


@app.route("/notes", methods=["POST"])
def update_notes():
    hexcode = request.form.get("hex", "").strip().upper()
    if hexcode:
        aircraft_notes[hexcode] = {
            "corridor": request.form.get("corridor", "").strip(),
            "frequency": request.form.get("frequency", "").strip(),
            "remarks": request.form.get("remarks", "").strip()
        }
        save_notes(aircraft_notes)

    return redirect(url_for("logs"))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
