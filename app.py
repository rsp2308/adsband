from flask import Flask, render_template_string
import requests
from datetime import datetime

app = Flask(__name__)

seen = set()

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>ADS-B Dashboard</title>
    <meta http-equiv="refresh" content="5">

    <style>
        body{
            background:#0f172a;
            color:white;
            font-family:Arial,sans-serif;
            margin:20px;
        }

        h1{
            color:#38bdf8;
        }

        .card{
            background:#1e293b;
            padding:15px;
            border-radius:10px;
            margin-bottom:20px;
            font-size:22px;
        }

        table{
            width:100%;
            border-collapse:collapse;
        }

        th{
            background:#334155;
        }

        td,th{
            border:1px solid #475569;
            padding:8px;
            text-align:center;
        }

        tr:nth-child(even){
            background:#1e293b;
        }

        tr:hover{
            background:#334155;
        }
    </style>

</head>
<body>

<h1>✈ Roshan ADS-B Dashboard</h1>

<div class="card">
Aircraft Visible: {{ count }}
</div>

<table>
<tr>
<th>Flight</th>
<th>HEX</th>
<th>Altitude</th>
<th>Speed</th>
<th>Track</th>
<th>Latitude</th>
<th>Longitude</th>
<th>Messages</th>
</tr>

{% for p in planes %}
<tr>
<td>{{ p.get('flight','') }}</td>
<td>{{ p.get('hex','') }}</td>
<td>{{ p.get('altitude','') }}</td>
<td>{{ p.get('speed','') }}</td>
<td>{{ p.get('track','') }}</td>
<td>{{ p.get('lat','') }}</td>
<td>{{ p.get('lon','') }}</td>
<td>{{ p.get('messages','') }}</td>
</tr>
{% endfor %}

</table>

</body>
</html>
"""

@app.route("/")
def home():

    global seen

    try:

        data = requests.get(
            "http://127.0.0.1:8080/data.json",
            timeout=5
        ).json()

        for plane in data:

            hexcode = plane.get("hex", "")

            if hexcode and hexcode not in seen:

                seen.add(hexcode)

                flight = plane.get("flight", "").strip()
                alt = plane.get("altitude", "?")
                speed = plane.get("speed", "?")
                lat = plane.get("lat", "?")
                lon = plane.get("lon", "?")

                logline = (
                    f"{datetime.now()} | "
                    f"{flight} | "
                    f"{hexcode} | "
                    f"ALT:{alt} | "
                    f"SPD:{speed} | "
                    f"LAT:{lat} | "
                    f"LON:{lon}\n"
                )

                print(logline.strip())

                with open(
                    "flight_log.txt",
                    "a",
                    encoding="utf-8"
                ) as f:
                    f.write(logline)

        return render_template_string(
            HTML,
            planes=data,
            count=len(data)
        )

    except Exception as e:
        return f"<h1>Error</h1><pre>{e}</pre>"

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )