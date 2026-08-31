# ADS-B Control Dashboard

A lightweight **ADS-B airspace surveillance dashboard** built with Python and Flask. It reads aircraft data from a local `dump1090` / `readsb` JSON feed, maintains an in-memory aircraft tracker, and presents live traffic in a professional aviation-style web interface.

## Features

- Live aircraft tracking from a local ADS-B JSON feed
- Flask web dashboard with an EFIS-inspired dark interface
- Aircraft status classification: **active, stale, offline**
- Callsign, ICAO HEX, squawk, category, altitude, vertical rate, speed, track, latitude and longitude
- Emergency squawk detection for **7500, 7600 and 7700**
- Altitude trend indicator based on vertical rate
- RSSI signal-strength bar display
- Automatic nearest ATC facility and frequency estimation from aircraft coordinates
- Manual frequency, corridor and remarks annotations
- FlightAware links for tracked aircraft
- Search/filter by callsign, HEX code or squawk
- Clickable column sorting
- Automatic 5-second dashboard refresh
- Persistent flight logging to `flight_log.txt`
- CSV export of logs
- Separate log-analysis page

## Architecture

```text
ADS-B Receiver
(dump1090 / readsb)
        │
        │ HTTP JSON
        │ 127.0.0.1:8080/data.json
        ▼
┌──────────────────────────────┐
│          Flask App           │
│                              │
│ Feed refresh                 │
│ Aircraft state tracking      │
│ Squawk detection             │
│ ATC frequency lookup         │
│ Altitude / RSSI processing   │
│ Logging & annotations        │
└──────────────┬───────────────┘
               │
               ▼
      ┌─────────────────┐
      │  Web Dashboard  │
      │                 │
      │ Live Traffic    │
      │ Log Analysis    │
      │ CSV Export      │
      └─────────────────┘
```

The application consumes `http://127.0.0.1:8080/data.json`, updates an in-memory aircraft store, enriches each track with derived information, and renders the dashboard.

## Repository Structure

```text
adsband/
├── app.py                 # Main Flask dashboard
├── ads.py                 # ADS-B payload detection / classification helpers
├── ads_dash.py            # Lightweight live aircraft console logger
├── ads_rec.py             # Aircraft logger with persistent flight log
├── aircraft_notes.json    # Saved aircraft annotations
├── flight_log.txt         # Recorded aircraft observations
└── test.py                # Basic SDR environment test
```

## ADS-B Detection Helper

`ads.py` provides a small stateful detector for hexadecimal Mode S / ADS-B payloads. It normalizes input, checks for valid 7- or 14-byte messages and Downlink Format 17, extracts the ADS-B type code, classifies message kinds, and maintains simple detection statistics.

Example:

```bash
python ads.py 8D40621D58C382D690C8AC2863A7
```

The module also exposes `ADSBDetector` and `detect_stream()` for programmatic use.

## Data Source

The dashboard expects an ADS-B receiver such as **dump1090** or **readsb** to expose aircraft information through:

```text
http://127.0.0.1:8080/data.json
```

The application handles feed errors and can continue displaying the last-known traffic while the receiver feed is unavailable.

## Dashboard Logic

### Aircraft Status

Tracks are classified from the time since their most recent observation:

| Status | Age |
|---|---:|
| Active | ≤ 20 s |
| Stale | > 20 s and ≤ 90 s |
| Offline | > 90 s |

Aircraft records remain in the in-memory store so short feed gaps do not immediately remove them.

### Emergency Squawk Detection

| Squawk | Alert |
|---|---|
| `7500` | HIJACK |
| `7600` | RADIO FAIL |
| `7700` | EMERGENCY |

### ATC Frequency Estimation

For aircraft with valid latitude and longitude, the application computes great-circle distance to a built-in list of representative ATC facilities and displays the nearest facility, frequency, controller type, and approximate distance. Manual frequency entries can override the automatically selected frequency.

### Aircraft Category, Trend and RSSI

Aircraft category codes are converted into readable labels. Vertical rate is used to display climb, level or descent indicators, and RSSI values are mapped to a four-bar signal-strength display.

## Logging

`ads_rec.py` polls the receiver feed every 30 seconds and records newly observed ICAO HEX addresses with timestamp, callsign, altitude and speed in `flight_log.txt`.

`ads_dash.py` is a simpler console monitor that polls every 10 seconds and prints visible aircraft with callsign, altitude and speed.

## Web Interface

The main Flask application provides two views:

### Live Traffic

Displays current tracked aircraft with:

- Callsign and FlightAware link
- Active / stale / offline state
- ICAO HEX and squawk
- Aircraft category
- Altitude and vertical-rate trend
- Airspeed and track
- Latitude / longitude
- RSSI and message count
- Nearest ATC frequency
- Corridor and timestamps

The page includes live search, sortable columns, an auto-refresh countdown, and CSV export.

### Log Analysis

The `/logs` page provides historical log analysis and supports aircraft annotations including corridor, remarks, and optional manual ATC frequency.

## CSV Export

Flight logs can be exported from:

```text
/export/csv
```

The export includes timestamp, event type, callsign, HEX, altitude, speed, coordinates, corridor, frequency and remarks.

## Requirements

The main application uses:

- Python 3
- Flask
- Requests

Install the Python dependencies with:

```bash
pip install flask requests
```

You also need a local ADS-B receiver providing the expected `data.json` endpoint. The receiver/decoder itself is not included in this repository.

## Installation

```bash
git clone https://github.com/rsp2308/adsband.git
cd adsband
pip install flask requests
```

Start your ADS-B receiver so that this endpoint is available:

```text
http://127.0.0.1:8080/data.json
```

## Run the Dashboard

```bash
python app.py
```

The Flask server listens on:

```text
0.0.0.0:5000
```

Open:

```text
http://127.0.0.1:5000
```

## Project Stack

**Language:** Python  
**Web Framework:** Flask  
**HTTP/Data:** Requests, JSON  
**Data Source:** dump1090 / readsb `data.json` feed  
**Frontend:** HTML, CSS, JavaScript  
**Logging:** Text log + CSV export

## Project Scope

This repository focuses on **ADS-B visualization, aircraft tracking, alerting, annotation and logging** around a locally available receiver feed. It does not contain the RF receiver hardware or the underlying `dump1090` / `readsb` decoder.

## Possible Improvements

- Add a live map-based traffic display
- Move ATC facility data into a dedicated external dataset
- Add configurable receiver endpoint and refresh intervals
- Replace text-file logs with SQLite or another database
- Add automated unit tests for ADS-B parsing and dashboard logic
- Add `requirements.txt` and deployment configuration
- Add configurable geofencing and alert zones

## Author

**Roshan Parmar**  
GitHub: https://github.com/rsp2308
