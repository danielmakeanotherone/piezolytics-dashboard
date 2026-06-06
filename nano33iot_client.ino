// Piezolytics — Arduino Nano 33 IoT (WiFi, two-tile visit detection)
// Libraries needed (install via Arduino Library Manager):
//   - WiFiNINA
//   - ArduinoHttpClient
//   - ArduinoJson

#include <WiFiNINA.h>
#include <ArduinoHttpClient.h>
#include <ArduinoJson.h>

// ─── CONFIG ───
const char* SSID        = "YOUR_WIFI_SSID";
const char* PASSWORD    = "YOUR_WIFI_PASSWORD";
const char* SERVER_IP   = "172.20.10.3";
const int   SERVER_PORT = 8080;
static const char* TILE_ID = "tile_1";   // change per device

// ─── PINS ───
static const uint8_t PIN_A = A0;
static const uint8_t PIN_B = A1;

// ─── TUNING (Nano 33 IoT = 10-bit ADC, 0–1023) ───
const int THRESHOLD      = 200;
const int CONFIRM_WINDOW = 2000;
const int PRESS_HOLD     = 80;
const int MIN_DWELL      = 80;
const int COOLDOWN       = 90;

// ─── STATE ───
bool          tileAActive      = false;
bool          tileBActive      = false;
int           tileAPeak        = 0;
int           tileBPeak        = 0;
unsigned long tileAOnTime      = 0;
unsigned long tileBOnTime      = 0;
unsigned long tileALastSeen    = 0;
unsigned long tileBLastSeen    = 0;
unsigned long tileAOffTime     = 0;
unsigned long tileBOffTime     = 0;
bool          waitingForSecond = false;
unsigned long waitStart        = 0;
int           firstTile        = 0;
unsigned long lastVisit        = 0;

bool pendingSend   = false;
int  pendingPeakA  = 0;
int  pendingDwellA = 0;
int  pendingPeakB  = 0;
int  pendingDwellB = 0;
int  pendingOrder  = 0;

WiFiClient wifi;
HttpClient http(wifi, SERVER_IP, SERVER_PORT);

// ─── RESET ───
void resetState() {
  tileAActive = tileBActive = false;
  tileAPeak = tileBPeak = 0;
  tileAOnTime = tileBOnTime = 0;
  tileALastSeen = tileBLastSeen = 0;
  tileAOffTime = tileBOffTime = 0;
  waitingForSecond = false;
  waitStart = firstTile = 0;
}

// ─── READ ───
int readPin(int pin) {
  int peak = 0;
  for (int i = 0; i < 4; i++) {
    int v = analogRead(pin);
    if (v > peak) peak = v;
    delayMicroseconds(100);
  }
  return peak;
}

// ─── SEND ───
void sendVisit(int peakA, int dwellA, int peakB, int dwellB, int order) {
  if (WiFi.status() != WL_CONNECTED) return;

  StaticJsonDocument<256> doc;
  doc["tile_id"]         = TILE_ID;
  doc["event_type"]      = "VISIT";
  doc["tile_a_peak"]     = peakA;
  doc["tile_a_dwell_ms"] = dwellA;
  doc["tile_b_peak"]     = peakB;
  doc["tile_b_dwell_ms"] = dwellB;
  doc["first_tile"]      = order;
  doc["confidence"]      = "high";

  String body;
  serializeJson(doc, body);

  http.post("/data", "application/json", body);
  int code = http.responseStatusCode();
  http.responseBody();
  Serial.print("POST => HTTP "); Serial.println(code);
}

void connectWiFi() {
  WiFi.disconnect();
  delay(1000);
  WiFi.begin(SSID, PASSWORD);
  Serial.print("Connecting to WiFi");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("\nConnected: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nFailed — retrying in 5s...");
    delay(5000);
    connectWiFi();
  }
}

// ─── SETUP ───
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("=== Piezolytics — Nano 33 IoT " + String(TILE_ID) + " ===");
  connectWiFi();
}

// ─── LOOP ───
void loop() {
  unsigned long now = millis();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi lost — reconnecting...");
    connectWiFi();
    return;
  }

  if (pendingSend) {
    pendingSend = false;
    sendVisit(pendingPeakA, pendingDwellA, pendingPeakB, pendingDwellB, pendingOrder);
    return;
  }

  int valA = readPin(PIN_A);
  int valB = readPin(PIN_B);

  Serial.print("A: "); Serial.print(valA);
  Serial.print("  B: "); Serial.println(valB);

  if (lastVisit > 0 && (now - lastVisit) < (unsigned long)COOLDOWN) {
    delay(3);
    return;
  }

  // ── Tile A ──
  if (valA > THRESHOLD) {
    tileALastSeen = now;
    if (!tileAActive) {
      tileAActive = true; tileAOnTime = now; tileAPeak = valA;
      if (!waitingForSecond) { waitingForSecond = true; waitStart = now; firstTile = 1; }
    } else if (valA > tileAPeak) { tileAPeak = valA; }
  } else if (tileAActive && (now - tileALastSeen) > (unsigned long)PRESS_HOLD) {
    tileAOffTime = now; tileAActive = false;
    if (waitingForSecond && firstTile == 2) {
      int dwellA = (int)(tileAOffTime - tileAOnTime);
      int dwellB = (int)(tileBOffTime - tileBOnTime);
      if (dwellA > MIN_DWELL && (now - waitStart) <= (unsigned long)CONFIRM_WINDOW) {
        pendingPeakA = tileAPeak; pendingDwellA = dwellA;
        pendingPeakB = tileBPeak; pendingDwellB = dwellB;
        pendingOrder = 2; pendingSend = true;
        lastVisit = now; resetState();
      }
    }
  }

  // ── Tile B ──
  if (valB > THRESHOLD) {
    tileBLastSeen = now;
    if (!tileBActive) {
      tileBActive = true; tileBOnTime = now; tileBPeak = valB;
      if (!waitingForSecond) {
        waitingForSecond = true; waitStart = now; firstTile = 2;
      } else if (firstTile == 1 && (now - waitStart) <= (unsigned long)CONFIRM_WINDOW) {
        int dwellA = tileAActive ? (int)(now - tileAOnTime) : (int)(tileAOffTime - tileAOnTime);
        if (dwellA > MIN_DWELL) {
          pendingPeakA = tileAPeak; pendingDwellA = dwellA;
          pendingPeakB = tileBPeak; pendingDwellB = 0;
          pendingOrder = 1; pendingSend = true;
          lastVisit = now; resetState();
        }
      }
    } else if (valB > tileBPeak) { tileBPeak = valB; }
  } else if (tileBActive && (now - tileBLastSeen) > (unsigned long)PRESS_HOLD) {
    tileBOffTime = now; tileBActive = false;
  }

  // ── Expire window ──
  if (waitingForSecond && (now - waitStart) > (unsigned long)CONFIRM_WINDOW) resetState();

  delay(3);
}
