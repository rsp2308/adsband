import requests
import time

print("ADS-B Dashboard Logger Started")

while True:
    try:
        data = requests.get(
            "http://127.0.0.1:8080/data.json"
        ).json()

        print(f"Aircraft Visible: {len(data)}")

        for plane in data:
            flight = plane.get("flight", "").strip()
            alt = plane.get("altitude", "?")
            speed = plane.get("speed", "?")

            if flight:
                print(f"{flight} ALT:{alt} SPD:{speed}")

        print("-" * 40)

    except Exception as e:
        print("ERROR:", e)

    time.sleep(10)