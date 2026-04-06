# Food Freshness Estimator with Edge Intelligence

A smart IoT-based system that predicts food freshness using sensor data and machine learning, deployed on edge devices like Raspberry Pi.

---

## 📌 Overview

This project uses environmental and gas sensor data to estimate the freshness level of food (Fresh / Acceptable / Spoiled). It combines:

- 📡 IoT Sensors (DHT22, MQ-2)
- 🤖 Machine Learning Models
- 🖥️ Edge Deployment (Raspberry Pi)
- 🌐 Web Interface (Flask)

---

## 🚀 Features

- Real-time freshness prediction
- Edge-based processing (low latency, offline capable)
- Sensor data logging and storage
- Web interface for user interaction
- Multiple ML models (Logistic Regression, Decision Tree)

---

## 🧠 Machine Learning

Models used:
- Logistic Regression
- Decision Tree Classifier

Input features:
- Gas sensor readings (MQ-2)
- Temperature (°C)
- Humidity (%)
- Elapsed time
- Storage condition

Output:
- `Fresh`
- `Acceptable`
- `Spoiled`

---

## 🏗️ System Architecture


Sensors → Raspberry Pi → ML Model → Flask Server → Web UI
↓
SQLite DB


---

## 📂 Project Structure
freshness_project/

│
├── app.py

├── freshness_decision_tree.pkl

├── freshness_logistic_regression.pkl

├── freshness.db

│

├── templates/

│ └── index.html

│

├── static/

│ └── style.css

│

└── dataset/

└── freshness_data.csv


---

## ⚙️ Installation (Raspberry Pi / Linux)

### 1. Clone Repository
#### bash
git clone https://github.com/your-username/food-freshness-estimator.git

cd food-freshness-estimator 

### 2. Create Virtual Environment
python3 -m venv venv

source venv/bin/activate

### 3. Install Dependencies
pip install -r requirements.txt

▶️ Run the Application

python app.py

#### Open in browser:

http://<raspberry-pi-ip>:5000

🌐 Production Deployment

#### Use Gunicorn + Nginx:
gunicorn -w 3 -b 127.0.0.1:8000 app:app

#### 🗄️ Database
SQLite used for local storage

Stores:

- Sensor readings
- Predictions
- Timestamped logs

#### 🧪 Sample Input
- Food Type: Apple
- Gas Raw:	539
- Temperature:	28.5°C
- Humidity:	65%
- Time:	360 mins
- Storage:	Room

#### Output:
Prediction: Acceptable

## 🔧 Hardware Requirements
- Raspberry Pi (Recommended: Pi 4/5)
- DHT22 Sensor (Temperature & Humidity)
- MQ-2 Gas Sensor
- Power Supply

## 📈 Future Improvements
- Real-time sensor integration (GPIO)
- Mobile app interface
- Cloud synchronization
- Model retraining pipeline
- Data visualization dashboard

## 👨‍💻 Authors
Medhini

Tanusshree Avirtha Vijay

Shreenidhi S

## 📄 License
This project is licensed under the MIT License.

## ⭐ Acknowledgements
Scikit-learn

Flask

Raspberry Pi Foundation
