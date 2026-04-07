from collections import deque
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import pandas as pd
import joblib
import threading
import time
import random

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "food-freshness-demo-secret-key"

model = joblib.load("freshness_decision_tree.pkl")

recent_readings = deque(maxlen=20)
data_lock = threading.Lock()

last_esp_update = 0
current_mode = "DEMO"
current_demo_environment = "fridge"

LABEL_SCORE_MAP = {
    "fresh": 100.0,
    "acceptable": 50.0,
    "medium": 50.0,
    "spoiled": 0.0,
}

ESP_TIMEOUT_SECONDS = 15
DEMO_INTERVAL_SECONDS = 10

DEMO_ENVIRONMENTS = {
    "fridge": {
        "temperature": (2.0, 8.0),
        "humidity": (68.0, 88.0),
        "gas": (80.0, 165.0),
    },
    "room": {
        "temperature": (24.0, 32.0),
        "humidity": (45.0, 70.0),
        "gas": (120.0, 260.0),
    },
    "sunlight": {
        "temperature": (30.0, 42.0),
        "humidity": (28.0, 55.0),
        "gas": (180.0, 360.0),
    },
}

SAFE_TIME_BASELINES = {
    "fridge": {"base_minutes": 2400, "gas_ref": 460, "temp_ref": 5.8, "humidity_ref": 85.1},
    "room": {"base_minutes": 1440, "gas_ref": 753, "temp_ref": 29.0, "humidity_ref": 76.5},
    "sun": {"base_minutes": 960, "gas_ref": 1014, "temp_ref": 39.3, "humidity_ref": 70.7},
    "sunlight": {"base_minutes": 960, "gas_ref": 1014, "temp_ref": 39.3, "humidity_ref": 70.7},
}


def seed_demo_readings(environment="fridge"):
    bounds = DEMO_ENVIRONMENTS.get(environment, DEMO_ENVIRONMENTS["fridge"])
    for _ in range(5):
        recent_readings.append({
            "temperature_c": round(random.uniform(*bounds["temperature"]), 2),
            "humidity_percent": round(random.uniform(*bounds["humidity"]), 2),
            "gas_raw": round(random.uniform(*bounds["gas"]), 2),
            "source": "demo",
            "environment": environment,
            "timestamp": time.time()
        })


seed_demo_readings(current_demo_environment)


def normalize_label(label):
    return str(label).strip().lower()


def normalize_storage(storage_condition):
    value = str(storage_condition).strip().lower()
    if value == "sunlight":
        return "sun"
    return value


def compute_freshness_score(classes, probabilities):
    score = 0.0
    for label, prob in zip(classes, probabilities):
        score += LABEL_SCORE_MAP.get(normalize_label(label), 0.0) * float(prob)
    return max(0.0, min(100.0, score))


def estimate_remaining_safe_time(storage_condition, elapsed_time_minutes, gas_raw, temperature_c, humidity_percent):
    storage_key = normalize_storage(storage_condition)
    params = SAFE_TIME_BASELINES.get(storage_key, SAFE_TIME_BASELINES["room"])

    base_minutes = params["base_minutes"]
    gas_ref = params["gas_ref"]
    temp_ref = params["temp_ref"]
    humidity_ref = params["humidity_ref"]

    remaining = (
        base_minutes
        - float(elapsed_time_minutes)
        - 2.0 * (float(gas_raw) - gas_ref)
        - 25.0 * (float(temperature_c) - temp_ref)
        - 10.0 * (float(humidity_percent) - humidity_ref)
    )

    remaining = max(0.0, round(remaining, 2))
    remaining_hours = round(remaining / 60.0, 2)
    return remaining, remaining_hours


def append_reading(temperature_c, humidity_percent, gas_raw, source="demo", environment=None):
    with data_lock:
        recent_readings.append({
            "temperature_c": float(temperature_c),
            "humidity_percent": float(humidity_percent),
            "gas_raw": float(gas_raw),
            "source": source,
            "environment": environment,
            "timestamp": time.time()
        })


def get_mode():
    global current_mode
    if time.time() - last_esp_update <= ESP_TIMEOUT_SECONDS:
        current_mode = "LIVE"
    else:
        current_mode = "DEMO"
    return current_mode


def get_demo_environment():
    return current_demo_environment


def set_demo_environment(environment):
    global current_demo_environment
    if environment in DEMO_ENVIRONMENTS:
        current_demo_environment = environment


def clamp(value, low, high):
    return max(low, min(high, value))


def generate_demo_reading():
    environment = get_demo_environment()
    bounds = DEMO_ENVIRONMENTS.get(environment, DEMO_ENVIRONMENTS["fridge"])

    with data_lock:
        demo_only = [item for item in recent_readings if item.get("source") == "demo"]
        last_demo = demo_only[-1] if demo_only else None

    if last_demo:
        base_temp = float(last_demo["temperature_c"])
        base_humidity = float(last_demo["humidity_percent"])
        base_gas = float(last_demo["gas_raw"])
    else:
        base_temp = sum(bounds["temperature"]) / 2
        base_humidity = sum(bounds["humidity"]) / 2
        base_gas = sum(bounds["gas"]) / 2

    temperature_c = round(clamp(base_temp + random.uniform(-1.2, 1.2), *bounds["temperature"]), 2)
    humidity_percent = round(clamp(base_humidity + random.uniform(-3.0, 3.0), *bounds["humidity"]), 2)
    gas_raw = round(clamp(base_gas + random.uniform(-18.0, 22.0), *bounds["gas"]), 2)

    append_reading(
        temperature_c=temperature_c,
        humidity_percent=humidity_percent,
        gas_raw=gas_raw,
        source="demo",
        environment=environment
    )


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

    remaining_minutes, remaining_hours = estimate_remaining_safe_time(
        storage_condition=storage_condition,
        elapsed_time_minutes=elapsed_time_minutes,
        gas_raw=gas_raw,
        temperature_c=temperature_c,
        humidity_percent=humidity_percent
    )

    append_reading(
        temperature_c=float(temperature_c),
        humidity_percent=float(humidity_percent),
        gas_raw=float(gas_raw),
        source=source,
        environment=None
    )

    return prediction, probabilities, freshness_score, remaining_minutes, remaining_hours


def get_chart_data():
    with data_lock:
        readings = list(recent_readings)

    return {
        "labels": list(range(1, len(readings) + 1)),
        "temperature": [round(float(item["temperature_c"]), 2) for item in readings],
        "humidity": [round(float(item["humidity_percent"]), 2) for item in readings],
        "gas": [round(float(item["gas_raw"]), 2) for item in readings],
    }


def get_last_three_readings():
    mode = get_mode()

    with data_lock:
        readings = list(recent_readings)

    if mode == "LIVE":
        live_readings = [item for item in readings if item.get("source") == "esp"]
        if live_readings:
            return live_readings[-3:][::-1]

    return readings[-3:][::-1]


def serialize_readings(readings):
    return [
        {
            "temperature_c": round(float(item["temperature_c"]), 2),
            "humidity_percent": round(float(item["humidity_percent"]), 2),
            "gas_raw": round(float(item["gas_raw"]), 2),
            "source": item.get("source"),
            "environment": item.get("environment")
        }
        for item in readings
    ]


def default_form_data():
    return {
        "food_type": "",
        "storage_condition": "fridge",
        "gas_raw": "",
        "temperature_c": "",
        "humidity_percent": "",
        "elapsed_time_minutes": ""
    }


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        try:
            food_type = request.form["food_type"]
            storage_condition = request.form["storage_condition"]
            gas_raw = float(request.form["gas_raw"])
            temperature_c = float(request.form["temperature_c"])
            humidity_percent = float(request.form["humidity_percent"])
            elapsed_time_minutes = float(request.form["elapsed_time_minutes"])

            session["form_data"] = {
                "food_type": food_type,
                "storage_condition": storage_condition,
                "gas_raw": request.form["gas_raw"],
                "temperature_c": request.form["temperature_c"],
                "humidity_percent": request.form["humidity_percent"],
                "elapsed_time_minutes": request.form["elapsed_time_minutes"]
            }

            prediction, probabilities, freshness_score, remaining_minutes, remaining_hours = run_prediction(
                food_type=food_type,
                storage_condition=storage_condition,
                gas_raw=gas_raw,
                temperature_c=temperature_c,
                humidity_percent=humidity_percent,
                elapsed_time_minutes=elapsed_time_minutes,
                source="manual"
            )

            session["prediction_result"] = {
                "prediction": str(prediction),
                "probabilities": probabilities,
                "freshness_score": float(freshness_score),
                "remaining_minutes": float(remaining_minutes),
                "remaining_hours": float(remaining_hours)
            }

            session.pop("error_message", None)
            return redirect(url_for("index"))

        except Exception as exc:
            session["error_message"] = str(exc)
            return redirect(url_for("index"))

    prediction_data = session.get("prediction_result", {})
    error_message = session.get("error_message")
    form_data = session.get("form_data", default_form_data())

    prediction = prediction_data.get("prediction")
    probabilities = prediction_data.get("probabilities", [])
    freshness_score = prediction_data.get("freshness_score")
    remaining_minutes = prediction_data.get("remaining_minutes")
    remaining_hours = prediction_data.get("remaining_hours")

    chart_data = get_chart_data()
    past_three_readings = get_last_three_readings()
    mode = get_mode()

    return render_template(
        "home.html",
        prediction=prediction,
        probabilities=probabilities,
        freshness_score=freshness_score,
        remaining_minutes=remaining_minutes,
        remaining_hours=remaining_hours,
        error_message=error_message,
        recent_readings=past_three_readings,
        chart_data=chart_data,
        mode=mode,
        demo_environment=get_demo_environment(),
        form_data=form_data
    )


@app.route("/clear-session", methods=["GET"])
def clear_session():
    session.pop("prediction_result", None)
    session.pop("error_message", None)
    return redirect(url_for("index"))


@app.route("/set-demo-environment", methods=["POST"])
def set_demo_environment_route():
    environment = request.form.get("demo_environment", "fridge").strip().lower()
    set_demo_environment(environment)
    return redirect(url_for("index"))


@app.route("/api/dashboard-data", methods=["GET"])
def dashboard_data():
    mode = get_mode()
    past_three_readings = get_last_three_readings()
    chart_data = get_chart_data()

    return jsonify({
        "mode": mode,
        "demo_environment": get_demo_environment(),
        "recent_readings": serialize_readings(past_three_readings),
        "chart_data": chart_data
    })


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

        prediction, probabilities, freshness_score, remaining_minutes, remaining_hours = run_prediction(
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
            "remaining_minutes": float(remaining_minutes),
            "remaining_hours": float(remaining_hours),
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
    return jsonify({
        "mode": get_mode(),
        "demo_environment": get_demo_environment()
    })


if __name__ == "__main__":
    worker = threading.Thread(target=demo_data_worker, daemon=True)
    worker.start()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
