#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <ESPmDNS.h>

// ─── FILL THESE IN ───────────────────────────────────────────────────────────
const char* SSID     = "Danielp";
const char* PASSWORD = "asdfghjk";
// ─────────────────────────────────────────────────────────────────────────────

const char* SERVER   = "http://Daniels-MacBook-Air-10.local:8080/data";
static const char* TILE_ID = "tile_2";

// ─── PINS ───
static const uint8_t PIN_A = 34;
static const uint8_t PIN_B = 35;

// ─── TUNING (ESP32 = 12-bit ADC, 0–4095) ───
const int THRESHOLD      = 500;
const int CONFIRM_WINDOW = 2000;
const int PRESS_HOLD     = 80;
const int MIN_DWELL      = 150;
const int COOLDOWN       = 3000;

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

void resetState() {
  tileAActive = tileBActive = false;
  tileAPeak = tileBPeak = 0;
  tileAOnTime = tileBOnTime = tileALastSeen = tileBLastSeen = 0;
  tileAOffTime = tileBOffTime = 0;
  waitingForSecond = false;
  waitStart = firstTile = 0;
}

int readPin(int pin) {
  int peak = 0;
  for (int i = 0; i < 4; i++) {
    int v = analogRead(pin);
    if (v > peak) peak = v;
    delayMicroseconds(100);
  }
  return peak;
}

void sendVisit(int peakA, int dwellA, int peakB, int dwellB, int order) {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    return;
  }

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

  HTTPClient http;
  http.setTimeout(4000);
  http.begin(SERVER);
  http.addHeader("Content-Type", "application/json");
  http.POST(body);
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n=== Piezolytics ESP32 " + String(TILE_ID) + " ===");
  Serial.print("Connecting to WiFi: ");
  Serial.println(SSID);

  WiFi.begin(SSID, PASSWORD);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 30) {
    delay(500);
    Serial.print(".");
    tries++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nFAILED to connect — check SSID/PASSWORD and reflash");
    // keep running so you can see the message; visits will be skipped
  } else {
    Serial.println("\nConnected: " + WiFi.localIP().toString());
    // start mDNS so we can resolve *.local hostnames
    MDNS.begin("tile2");
    Serial.println("Server: " + String(SERVER));
  }
}

void loop() {
  unsigned long now = millis();

  if (pendingSend) {
    pendingSend = false;
    sendVisit(pendingPeakA, pendingDwellA, pendingPeakB, pendingDwellB, pendingOrder);
    return;
  }

  if (lastVisit > 0 && (now - lastVisit) < (unsigned long)COOLDOWN) {
    delay(3);
    return;
  }

  int valA = readPin(PIN_A);
  int valB = readPin(PIN_B);

  // ── Tile A ──
  if (valA > THRESHOLD) {
    tileALastSeen = now;
    if (!tileAActive) {
      tileAActive = true;
      tileAOnTime = now;
      tileAPeak   = valA;
      Serial.print("Tile A ON — "); Serial.println(valA);
      if (!waitingForSecond) { waitingForSecond = true; waitStart = now; firstTile = 1; }
    } else if (valA > tileAPeak) {
      tileAPeak = valA;
    }
  } else if (tileAActive && (now - tileALastSeen) > (unsigned long)PRESS_HOLD) {
    tileAOffTime = now;
    tileAActive  = false;
    Serial.printf("Tile A OFF — peak %d  dwell %dms\n", tileAPeak, (int)(tileAOffTime - tileAOnTime));
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
      tileBActive = true;
      tileBOnTime = now;
      tileBPeak   = valB;
      Serial.print("Tile B ON — "); Serial.println(valB);
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
    } else if (valB > tileBPeak) {
      tileBPeak = valB;
    }
  } else if (tileBActive && (now - tileBLastSeen) > (unsigned long)PRESS_HOLD) {
    tileBOffTime = now;
    tileBActive  = false;
    Serial.printf("Tile B OFF — peak %d  dwell %dms\n", tileBPeak, (int)(tileBOffTime - tileBOnTime));
  }

  if (waitingForSecond && (now - waitStart) > (unsigned long)CONFIRM_WINDOW) {
    Serial.println("Timeout — only one tile triggered, ignored");
    resetState();
  }

  delay(3);
}
