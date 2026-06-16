import requests
import time
from datetime import datetime

print("ADS-B logger started")

seen = set()

while True:
    try:
        r = requests.get("http://127.0.0.1:8080/data.json", timeout=5)
        data = r.json()

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Aircraft visible: {len(data)}")

        for plane in data:
            hexcode = plane.get("hex", "")

            if hexcode and hexcode not in seen:
                seen.add(hexcode)

                flight = plane.get("flight", "").strip()
                alt = plane.get("altitude", "?")
                speed = plane.get("speed", "?")

                line = f"{datetime.now()} | {flight} | {hexcode} | ALT:{alt} | SPD:{speed}"

                print(line)

                with open("flight_log.txt", "a", encoding="utf-8") as f:
                    f.write(line + "\n")

    except Exception as e:
        print("ERROR:", e)

    time.sleep(30)