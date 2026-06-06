#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// --- config ---
const char* SSID     = "YOUR_WIFI_SSID";
const char* PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER   = "http://172.20.10.3:8080/data";

// VP = GPIO36 (ADC1_CH0)  — quadrant A
// VN = GPIO39 (ADC1_CH3)  — quadrant B
// GND = GND
#define PIN_A  36   // VP
#define PIN_B  39   // VN

#define ADC_BITS     12            // ESP32 = 12-bit ADC (0–4095)
#define ADC_MAX      4095.0
#define VREF         3.3           // reference voltage
#define SAMPLES      16            // oversample & average to reduce noise
#define INTERVAL_MS  500           // send every 500 ms

// ---------------------------------------------------------------
float readVoltage(int pin) {
  long sum = 0;
  for (int i = 0; i < SAMPLES; i++) {
    sum += analogRead(pin);
    delayMicroseconds(100);
  }
  float avg = sum / (float)SAMPLES;
  return (avg / ADC_MAX) * VREF;
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(ADC_BITS);
  analogSetAttenuation(ADC_11db);  // full 0–3.3 V range

  WiFi.begin(SSID, PASSWORD);
  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConnected: " + WiFi.localIP().toString());
}

void loop() {
  float vA = readVoltage(PIN_A);   // VP / quadrant A
  float vB = readVoltage(PIN_B);   // VN / quadrant B
  float diff = vA - vB;            // differential across the two quadrants

  Serial.printf("VP=%.3fV  VN=%.3fV  diff=%.3fV\n", vA, vB, diff);

  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(SERVER);
    http.addHeader("Content-Type", "application/json");

    StaticJsonDocument<128> doc;
    doc["quad_A_V"]  = serialized(String(vA,  3));
    doc["quad_B_V"]  = serialized(String(vB,  3));
    doc["diff_V"]    = serialized(String(diff, 3));

    String body;
    serializeJson(doc, body);

    int code = http.POST(body);
    Serial.printf("POST => HTTP %d\n", code);
    http.end();
  }

  delay(INTERVAL_MS);
}
