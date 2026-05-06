// Piezolytics — Arduino Nano (two-tile visit detection)
// Identical logic to the ESP32 version; sends over USB Serial instead of WiFi.
//
// Wiring: Tile A piezo -> A0 & GND | Tile B piezo -> A1 & GND
//         Add 1MΩ resistor across each piezo pin and GND.
//
// NOTE: Nano ADC is 10-bit (0–1023). Original ESP32 was 12-bit (0–4095).
//       THRESHOLD 600/4095 ≈ 15% → ~150 on Nano. Tune to your signal.

// ─── CONFIG ───
static const char* TILE_ID = "tile_2";

// ─── PINS ───
static const uint8_t PIN_A = A0;
static const uint8_t PIN_B = A1;

// ─── TUNING ───
const int THRESHOLD      = 235;   // raise if false triggers, lower if misses
const int CONFIRM_WINDOW = 2000;
const int PRESS_HOLD     = 80;
const int MIN_DWELL      = 300;   // noise spikes are brief; real footsteps last 300ms+
const int COOLDOWN       = 3000;  // ignore everything for 3s after a confirmed visit

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

// ─── RESET ───
void resetState() {
  tileAActive      = false;
  tileBActive      = false;
  tileAPeak        = 0;
  tileBPeak        = 0;
  tileAOnTime      = 0;
  tileBOnTime      = 0;
  tileALastSeen    = 0;
  tileBLastSeen    = 0;
  tileAOffTime     = 0;
  tileBOffTime     = 0;
  waitingForSecond = false;
  waitStart        = 0;
  firstTile        = 0;
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
  Serial.println("=============================");
  Serial.println(">>> CONFIRMED VISIT <<<");
  Serial.print("    Tile ID: ");  Serial.println(TILE_ID);
  Serial.print("    Order: Tile "); Serial.print(order == 1 ? "A" : "B"); Serial.println(" first");
  Serial.print("    Tile A — peak: "); Serial.print(peakA); Serial.print("  dwell: "); Serial.print(dwellA); Serial.println("ms");
  Serial.print("    Tile B — peak: "); Serial.print(peakB); Serial.print("  dwell: "); Serial.print(dwellB); Serial.println("ms");
  Serial.println("=============================");

  // JSON line — parsed by server.py
  Serial.print("{");
  Serial.print("\"tile_id\":\"");     Serial.print(TILE_ID);  Serial.print("\",");
  Serial.print("\"event_type\":\"VISIT\",");
  Serial.print("\"tile_a_peak\":");   Serial.print(peakA);    Serial.print(",");
  Serial.print("\"tile_a_dwell_ms\":"); Serial.print(dwellA); Serial.print(",");
  Serial.print("\"tile_b_peak\":");   Serial.print(peakB);    Serial.print(",");
  Serial.print("\"tile_b_dwell_ms\":"); Serial.print(dwellB); Serial.print(",");
  Serial.print("\"first_tile\":");    Serial.print(order);    Serial.print(",");
  Serial.print("\"confidence\":\"high\"");
  Serial.println("}");
}

// ─── SETUP ───
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== Piezolytics — Nano " + String(TILE_ID) + " ===");
  Serial.println("Monitoring tiles...\n");
}

// ─── LOOP ───
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
      if (!waitingForSecond) {
        waitingForSecond = true;
        waitStart        = now;
        firstTile        = 1;
      }
    } else if (valA > tileAPeak) {
      tileAPeak = valA;
    }
  } else if (tileAActive && (now - tileALastSeen) > (unsigned long)PRESS_HOLD) {
    tileAOffTime = now;
    tileAActive  = false;
    Serial.print("Tile A OFF — peak: "); Serial.print(tileAPeak);
    Serial.print("  dwell: "); Serial.print((int)(tileAOffTime - tileAOnTime)); Serial.println("ms");

    if (waitingForSecond && firstTile == 2) {
      int dwellA = (int)(tileAOffTime - tileAOnTime);
      int dwellB = (int)(tileBOffTime - tileBOnTime);
      if (dwellA > MIN_DWELL && (now - waitStart) <= (unsigned long)CONFIRM_WINDOW) {
        pendingPeakA  = tileAPeak;
        pendingDwellA = dwellA;
        pendingPeakB  = tileBPeak;
        pendingDwellB = dwellB;
        pendingOrder  = 2;
        pendingSend   = true;
        lastVisit     = now;
        resetState();
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
        waitingForSecond = true;
        waitStart        = now;
        firstTile        = 2;
      } else if (firstTile == 1 && (now - waitStart) <= (unsigned long)CONFIRM_WINDOW) {
        int dwellA = tileAActive ? (int)(now - tileAOnTime) : (int)(tileAOffTime - tileAOnTime);
        int dwellB = 0;
        if (dwellA > MIN_DWELL) {
          pendingPeakA  = tileAPeak;
          pendingDwellA = dwellA;
          pendingPeakB  = tileBPeak;
          pendingDwellB = dwellB;
          pendingOrder  = 1;
          pendingSend   = true;
          lastVisit     = now;
          resetState();
        }
      }
    } else if (valB > tileBPeak) {
      tileBPeak = valB;
    }
  } else if (tileBActive && (now - tileBLastSeen) > (unsigned long)PRESS_HOLD) {
    tileBOffTime = now;
    tileBActive  = false;
    Serial.print("Tile B OFF — peak: "); Serial.print(tileBPeak);
    Serial.print("  dwell: "); Serial.print((int)(tileBOffTime - tileBOnTime)); Serial.println("ms");
  }

  // ── Expire window ──
  if (waitingForSecond && (now - waitStart) > (unsigned long)CONFIRM_WINDOW) {
    Serial.println("One tile only — false entry, ignored");
    resetState();
  }

  delay(3);
}
