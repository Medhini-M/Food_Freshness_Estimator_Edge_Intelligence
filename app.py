from collections import deque
from flask import Flask, render_template, request, jsonify
import pandas as pd
import joblib
import threading
import time
import random

app = Flask(__name__, template_folder="templates", static_folder="static")

model = joblib.load("freshness_decision_tree.pkl")

recent_readings = deque(maxlen=20)
data_lock = threading.Lock()

last_esp_update = 0
current_mode = "DEMO"

SAMPLE_READINGS = [
    {"temperature_c": 5.2, "humidity_percent": 78.0, "gas_raw": 120.0, "source": "demo"},
    {"temperature_c": 5.4, "humidity_percent": 77.5, "gas_raw": 126.0, "source": "demo"},
    {"temperature_c": 5.8, "humidity_percent": 76.8, "gas_raw": 138.0, "source": "demo"},
    {"temperature_c": 6.0, "humidity_percent": 76.0, "gas_raw": 142.0, "source": "demo"},
    {"temperature_c": 6.3, "humidity_percent": 75.6, "gas_raw": 151.0, "source": "demo"},
]

for item in SAMPLE_READINGS:
    recent_readings.append(item)

LABEL_SCORE_MAP = {
    "fresh": 100.0,
    "acceptable": 50.0,
    "medium": 50.0,
    "spoiled": 0.0,
}

ESP_TIMEOUT_SECONDS = 15
DEMO_INTERVAL_SECONDS = 10


def normalize_label(label):
    return str(label).strip().lower()


def compute_freshness_score(classes, probabilities):
    score = 0.0
    for label, prob in zip(classes, probabilities):
        score += LABEL_SCORE_MAP.get(normalize_label(label), 0.0) * float(prob)
    return max(0.0, min(100.0, score))


def append_reading(temperature_c, humidity_percent, gas_raw, source="demo"):
    with data_lock:
        recent_readings.append({
            "temperature_c": float(temperature_c),
            "humidity_percent": float(humidity_percent),
            "gas_raw": float(gas_raw),
            "source": source
        })


def get_mode():
    global current_mode
    if time.time() - last_esp_update <= ESP_TIMEOUT_SECONDS:
        current_mode = "LIVE"
    else:
        current_mode = "DEMO"
    return current_mode


def generate_demo_reading():
    with data_lock:
        if recent_readings:
            last = recent_readings[-1]
            base_temp = float(last["temperature_c"])
            base_humidity = float(last["humidity_percent"])
            base_gas = float(last["gas_raw"])
        else:
            base_temp = 6.0
            base_humidity = 76.0
            base_gas = 140.0

    temperature_c = round(max(0, base_temp + random.uniform(-0.4, 0.5)), 2)
    humidity_percent = round(min(100, max(0, base_humidity + random.uniform(-1.2, 1.2))), 2)
    gas_raw = round(max(0, base_gas + random.uniform(-8, 10)), 2)

    append_reading(temperature_c, humidity_percent, gas_raw, source="demo")


def demo_data_worker():
    while True:
        if get_mode() == "DEMO":
            generate_demo_reading()
        time.sleep(DEMO_INTERVAL_SECONDS)


def run_prediction(food_type, storage_condition, gas_raw, temperature_c, humidity_percent, elapsed_time_minutes, source="manual"):
    input_data = pd.DataFrame([{
        "elapsed_time_minutes": float(elapsed_time_minutes),
        "gas_raw": float(gas_raw),
        "temperature_c": float(temperature_c),
        "humidity_percent": float(humidity_percent),
        "food_type": str(food_type),
        "storage_condition": str(storage_condition),
    }])

    prediction = model.predict(input_data)[0]
    prob_array = model.predict_proba(input_data)[0]

    probabilities = [
        {
            "label": str(label),
            "probability": float(round(float(prob) * 100, 2))
        }
        for label, prob in zip(model.classes_, prob_array)
    ]

    freshness_score = round(compute_freshness_score(model.classes_, prob_array), 2)

    append_reading(
        temperature_c=float(temperature_c),
        humidity_percent=float(humidity_percent),
        gas_raw=float(gas_raw),
        source=source
    )

    return prediction, probabilities, freshness_score


def get_chart_data():
    with data_lock:
        readings = list(recent_readings)

    return {
        "labels": list(range(1, len(readings) + 1)),
        "temperature": [round(float(item["temperature_c"]), 2) for item in readings],
        "humidity": [round(float(item["humidity_percent"]), 2) for item in readings],
        "gas": [round(float(item["gas_raw"]), 2) for item in readings],
    }


@app.route("/", methods=["GET", "POST"])
def index():
    prediction = None
    probabilities = []
    freshness_score = None
    error_message = None

    if request.method == "POST":
        try:
            food_type = request.form["food_type"]
            storage_condition = request.form["storage_condition"]
            gas_raw = float(request.form["gas_raw"])
            temperature_c = float(request.form["temperature_c"])
            humidity_percent = float(request.form["humidity_percent"])
            elapsed_time_minutes = float(request.form["elapsed_time_minutes"])

            prediction, probabilities, freshness_score = run_prediction(
                food_type=food_type,
                storage_condition=storage_condition,
                gas_raw=gas_raw,
                temperature_c=temperature_c,
                humidity_percent=humidity_percent,
                elapsed_time_minutes=elapsed_time_minutes,
                source="manual"
            )
        except Exception as exc:
            error_message = str(exc)

    chart_data = get_chart_data()

    with data_lock:
        past_three = list(recent_readings)[-3:][::-1]

    mode = get_mode()

    return render_template(
        "home.html",
        prediction=prediction,
        probabilities=probabilities,
        freshness_score=freshness_score,
        error_message=error_message,
        recent_readings=past_three,
        chart_data=chart_data,
        mode=mode
    )


@app.route("/api/esp-data", methods=["POST"])
def receive_esp_data():
    global last_esp_update

    try:
        data = request.get_json()

        if not data:
            return jsonify({"status": "error", "message": "No JSON payload received"}), 400

        required_fields = [
            "food_type",
            "storage_condition",
            "gas_raw",
            "temperature_c",
            "humidity_percent",
            "elapsed_time_minutes"
        ]

        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return jsonify({
                "status": "error",
                "message": f"Missing fields: {', '.join(missing_fields)}"
            }), 400

        food_type = data["food_type"]
        storage_condition = data["storage_condition"]
        gas_raw = float(data["gas_raw"])
        temperature_c = float(data["temperature_c"])
        humidity_percent = float(data["humidity_percent"])
        elapsed_time_minutes = float(data["elapsed_time_minutes"])

        last_esp_update = time.time()

        prediction, probabilities, freshness_score = run_prediction(
            food_type=food_type,
            storage_condition=storage_condition,
            gas_raw=gas_raw,
            temperature_c=temperature_c,
            humidity_percent=humidity_percent,
            elapsed_time_minutes=elapsed_time_minutes,
            source="esp"
        )

        return jsonify({
            "status": "success",
            "mode": "LIVE",
            "prediction": str(prediction),
            "freshness_score": float(freshness_score),
            "probabilities": probabilities,
            "stored_readings": len(recent_readings)
        }), 200

    except Exception as exc:
        return jsonify({
            "status": "error",
            "message": str(exc)
        }), 500


@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({"mode": get_mode()})


if __name__ == "__main__":
    worker = threading.Thread(target=demo_data_worker, daemon=True)
    worker.start()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
