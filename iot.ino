#include <Wire.h>
#include <DHT.h>
#include <Adafruit_ADS1X15.h>

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <time.h>

#define DHTPIN 14
#define DHTTYPE DHT22

DHT dht(DHTPIN, DHTTYPE);
Adafruit_ADS1115 ads;

// WiFi credentials (avoid spaces ideally)
const char* ssid = "M_POCO X5 Pro";
const char* password = "MiNila24";

// Flask API endpoint
const char* server = "http://192.168.17.16:5000/api/esp-data";

// NTP settings
const char* ntpServer = "time.google.com";
const long gmtOffset_sec = 19800;
const int daylightOffset_sec = 0;

unsigned long startTime;

void setup() {

  Serial.begin(9600);
  delay(2000);

  Serial.println("Starting system...");

  Wire.begin(D2, D1);

  if (!ads.begin()) {
    Serial.println("ADS1115 NOT FOUND!");
    while (1);
  }

  Serial.println("ADS1115 OK");
  dht.begin();

  // ---------- WIFI ----------
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(1000);

  WiFi.begin(ssid, password);

  Serial.print("Connecting to WiFi");

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 30) {
    delay(1000);
    Serial.print(".");
    retries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nConnected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWiFi FAILED!");
  }

  // ---------- NTP TIME ----------
  configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);

  Serial.println("Syncing time...");
  time_t now = time(nullptr);

  int ntp_retries = 0;
  while (now < 100000 && ntp_retries < 20) {
    delay(500);
    Serial.print(".");
    now = time(nullptr);
    ntp_retries++;
  }

  if (now < 100000) {
    Serial.println("\nTime sync FAILED (continuing without it)");
  } else {
    Serial.println("\nTime synced!");
  }

  startTime = millis();
}

void loop() {

  delay(10000);  // change to 7200000 for 2 hours later

  /* ---------- TIME ---------- */

  time_t now = time(nullptr);
  struct tm* timeinfo = localtime(&now);

  char timeString[30];

  if (now > 100000) {
    strftime(timeString, sizeof(timeString), "%Y-%m-%d %H:%M:%S", timeinfo);
  } else {
    sprintf(timeString, "no_time");
  }

  float elapsedMinutes = (millis() - startTime) / 60000.0;

  Serial.print("Timestamp: ");
  Serial.println(timeString);

  Serial.print("Elapsed Time (min): ");
  Serial.println(elapsedMinutes);

  /* ---------- DHT22 ---------- */

  float humidity = dht.readHumidity();
  float temperature = dht.readTemperature();

  if (isnan(humidity) || isnan(temperature)) {
    Serial.println("DHT22 FAILED");
    return;
  }

  Serial.print("Temperature: ");
  Serial.print(temperature);
  Serial.print(" °C | Humidity: ");
  Serial.print(humidity);
  Serial.println(" %");

  /* ---------- MQ-2 ---------- */

  int16_t adcValue = ads.readADC_SingleEnded(0);

  // 🔥 SCALE ADC → 100 to 1250
  float gas_scaled = 100 + (adcValue * 1150.0 / 32767.0);

  Serial.print("ADC: ");
  Serial.print(adcValue);
  Serial.print(" | Scaled Gas: ");
  Serial.println(gas_scaled);

  Serial.println("---------------------------");

  /* ---------- SEND DATA ---------- */

  if (WiFi.status() == WL_CONNECTED) {

    WiFiClient client;
    HTTPClient http;

    http.begin(client, server);
    http.addHeader("Content-Type", "application/json");

    String json = "{";
    json += "\"food_type\":\"apple\",";
    json += "\"storage_condition\":\"room\",";
    json += "\"gas_raw\":" + String(gas_scaled, 2) + ",";
    json += "\"temperature_c\":" + String(temperature, 2) + ",";
    json += "\"humidity_percent\":" + String(humidity, 2) + ",";
    json += "\"elapsed_time_minutes\":" + String(elapsedMinutes, 2);
    json += "}";

    Serial.println("Sending JSON:");
    Serial.println(json);

    int response = http.POST(json);

    Serial.print("Server Response: ");
    Serial.println(response);

    http.end();
  } else {
    Serial.println("WiFi not connected");
  }
}