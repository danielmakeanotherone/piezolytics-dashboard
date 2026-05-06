#!/usr/bin/env python3
"""
Piezo serial server — reads JSON from Arduino Nano over USB, serves live dashboard.

Dependencies:
  pip3 install pyserial

Usage:
  python3 server.py                        # auto-detect serial port
  python3 server.py /dev/tty.usbmodem14101 # specify port explicitly

Endpoints:
  GET  /       — live dashboard (auto-refreshes every 2s)
  GET  /data   — all stored readings as JSON
  GET  /clear  — wipe stored data
"""

import json
import sys
import time
import threading
import glob
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import deque
from datetime import datetime

PORT         = 8080
BAUD_RATE    = 115200
MAX_READINGS = 200

readings: deque = deque(maxlen=MAX_READINGS)
readings_lock   = threading.Lock()


# ----------------------------------------------------------------- serial

def find_serial_port():
    candidates = (
        glob.glob("/dev/tty.usbmodem*") +
        glob.glob("/dev/tty.usbserial*") +
        glob.glob("/dev/ttyUSB*") +
        glob.glob("/dev/ttyACM*")
    )
    return candidates[0] if candidates else None


def serial_reader(port):
    try:
        import serial
    except ImportError:
        print("ERROR: pyserial not installed — run: pip3 install pyserial")
        return

    ser = None
    while True:
        # (re)connect
        if ser is None:
            try:
                ser = serial.Serial(port, BAUD_RATE, timeout=1)
                print(f"Serial port opened: {port} @ {BAUD_RATE} baud")
            except Exception as e:
                print(f"Waiting for device on {port}: {e}")
                time.sleep(2)
                continue

        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
        except Exception:
            print(f"Device disconnected — retrying {port}...")
            try:
                ser.close()
            except Exception:
                pass
            ser = None
            time.sleep(2)
            continue

        if not line:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        entry = {
            "ts":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "epoch": time.time(),
            **payload,
        }
        with readings_lock:
            readings.append(entry)


# ----------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {fmt % args}")

    def do_POST(self):
        if self.path == "/data":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                self._send(400, "application/json", b'{"error":"invalid JSON"}')
                return
            entry = {
                "ts":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "epoch": time.time(),
                **payload,
            }
            with readings_lock:
                readings.append(entry)
            self._send(200, "application/json", b'{"ok":true}')
        else:
            self._send(404, "text/plain", b"Not found")

    def do_GET(self):
        if self.path == "/":
            self._send(200, "text/html", DASHBOARD.encode())

        elif self.path == "/data":
            with readings_lock:
                data = list(readings)
            self._send(200, "application/json", json.dumps(data).encode())

        elif self.path == "/clear":
            with readings_lock:
                readings.clear()
            self._send(200, "application/json", b'{"ok":true}')

        else:
            self._send(404, "text/plain", b"Not found")

    def _send(self, code, content_type, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


# ----------------------------------------------------------------- dashboard

DASHBOARD = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Piezolytics</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0f1117; color: #e0e0e0; padding: 24px; }

  h1 { font-size: 22px; font-weight: 600; color: #fff; margin-bottom: 4px; }
  .subtitle { font-size: 13px; color: #666; margin-bottom: 20px; }

  .toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 24px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #3ecf8e;
         box-shadow: 0 0 6px #3ecf8e; animation: pulse 2s infinite; flex-shrink: 0; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .status-text { font-size: 13px; color: #666; flex: 1; }
  button { background: #1a1d27; color: #aaa; border: 1px solid #2a2d3a;
           padding: 7px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; }
  button:hover { background: #2a2d3a; color: #fff; }

  /* tile panels grid */
  .tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .tile-panel { background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 14px; padding: 20px; }
  .tile-panel.active { border-color: #4f8ef7; }
  .tile-header { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; }
  .tile-name { font-size: 16px; font-weight: 700; color: #fff; }
  .tile-dot { width: 8px; height: 8px; border-radius: 50%; background: #333; flex-shrink: 0; }
  .tile-dot.on { background: #3ecf8e; box-shadow: 0 0 6px #3ecf8e; }

  /* mini stat cards inside each panel */
  .mini-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 18px; }
  .mini-card { background: #12141c; border: 1px solid #1e2030; border-radius: 10px; padding: 14px; }
  .mini-card .label { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: #555; margin-bottom: 6px; }
  .mini-card .value { font-size: 26px; font-weight: 700; color: #fff; }
  .mini-card .sub   { font-size: 11px; color: #444; margin-top: 4px; }
  .mini-card.blue  .value { color: #4f8ef7; }
  .mini-card.green .value { color: #3ecf8e; }

  /* canvas */
  canvas { width: 100%; display: block; border-radius: 8px; }

  .section-label { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: #555; margin-bottom: 10px; }

  /* table */
  table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 16px; }
  th { text-align: left; padding: 6px 10px; color: #444; font-weight: 500;
       border-bottom: 1px solid #1e2030; font-size: 10px; text-transform: uppercase; letter-spacing: .06em; }
  td { padding: 7px 10px; border-bottom: 1px solid #161820; color: #bbb; }
  td:first-child { color: #777; font-size: 11px; }
  .badge { display: inline-block; padding: 2px 7px; border-radius: 20px; font-size: 10px; font-weight: 600; }
  .badge.ab { background: #1a3a5c; color: #4f8ef7; }
  .badge.ba { background: #1a3a20; color: #3ecf8e; }

  .empty { color: #333; text-align: center; padding: 28px; font-size: 13px; }
</style>
</head>
<body>

<h1>Piezolytics</h1>
<p class="subtitle">Live floor sensor analytics</p>

<div class="toolbar">
  <div class="dot" id="dot"></div>
  <span class="status-text" id="status">Connecting...</span>
  <button onclick="clearData()">Clear data</button>
  <button onclick="fetchData()">Refresh</button>
</div>

<div class="tiles" id="tile-grid"></div>

<script>
const TILES = [
  { key: "tile_1", label: "Tile 1" },
  { key: "tile_2", label: "Tile 2" },
  { key: "tile_3", label: "Tile 3" },
  { key: "tile_4", label: "Tile 4" },
];

// build panels on load
TILES.forEach(t => {
  const id = t.key.replace("_", "");
  document.getElementById("tile-grid").innerHTML += `
  <div class="tile-panel" id="panel-${id}">
    <div class="tile-header">
      <div class="tile-dot" id="tdot-${id}"></div>
      <span class="tile-name">${t.label}</span>
    </div>
    <div class="mini-cards">
      <div class="mini-card blue">
        <div class="label">Visits</div>
        <div class="value" id="${id}-total">—</div>
        <div class="sub">confirmed</div>
      </div>
      <div class="mini-card green">
        <div class="label">Avg Peak A</div>
        <div class="value" id="${id}-peak">—</div>
        <div class="sub">ADC units</div>
      </div>
    </div>
    <div class="section-label">Recent visits</div>
    <canvas id="c-${id}" height="80"></canvas>
    <table>
      <thead><tr><th>Time</th><th>Order</th><th>Peak A</th><th>Dwell A</th><th>Peak B</th><th>Dwell B</th></tr></thead>
      <tbody id="tb-${id}"></tbody>
    </table>
  </div>`;
});

function fetchData() {
  fetch("/data")
    .then(r => r.json())
    .then(rows => {
      const visits = rows.filter(r => r.event_type === "VISIT");
      TILES.forEach(t => renderTile(t, visits.filter(v => v.tile_id === t.key)));

      const dot = document.getElementById("dot");
      const anyData = visits.length > 0;
      dot.style.background = anyData ? "#3ecf8e" : "#555";
      dot.style.boxShadow  = anyData ? "0 0 6px #3ecf8e" : "none";
      document.getElementById("status").textContent =
        `${visits.length} total visit(s) — updated ${new Date().toLocaleTimeString()}`;
    })
    .catch(() => {
      document.getElementById("status").textContent = "Connection error";
      document.getElementById("dot").style.background = "#e05252";
    });
}

function renderTile(t, visits) {
  const id = t.key.replace("_", "");
  const total = visits.length;

  const tdot = document.getElementById("tdot-" + id);
  if (total > 0) { tdot.classList.add("on"); } else { tdot.classList.remove("on"); }

  const avgPeak = total
    ? Math.round(visits.reduce((acc, v) => acc + (v.tile_a_peak || 0), 0) / total)
    : "—";
  document.getElementById(id + "-total").textContent = total || "—";
  document.getElementById(id + "-peak").textContent  = avgPeak;

  drawSparkline(document.getElementById("c-" + id), visits);

  const tbody = document.getElementById("tb-" + id);
  const recent = [...visits].reverse().slice(0, 10);
  if (!recent.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">No data yet</td></tr>';
    return;
  }
  tbody.innerHTML = recent.map(v => {
    const order = v.first_tile === 1
      ? '<span class="badge ab">A→B</span>'
      : '<span class="badge ba">B→A</span>';
    return `<tr>
      <td>${(v.ts || "").split(" ")[1] || "—"}</td>
      <td>${order}</td>
      <td>${v.tile_a_peak ?? "—"}</td>
      <td>${v.tile_a_dwell_ms ?? "—"}ms</td>
      <td>${v.tile_b_peak ?? "—"}</td>
      <td>${v.tile_b_dwell_ms ?? "—"}ms</td>
    </tr>`;
  }).join("");
}

function drawSparkline(canvas, visits) {
  canvas.width  = canvas.offsetWidth;
  canvas.height = 80;
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  if (visits.length < 2) {
    ctx.fillStyle = "#222";
    ctx.font = "12px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(visits.length === 0 ? "No data yet" : "Need more data", w / 2, h / 2 + 4);
    return;
  }

  const t0   = visits[0].epoch;
  const tEnd = visits[visits.length - 1].epoch;
  const span = Math.max(tEnd - t0, 60);
  const B = 16;
  const counts = Array(B).fill(0);
  visits.forEach(v => {
    const idx = Math.min(Math.floor((v.epoch - t0) / (span / B)), B - 1);
    counts[idx]++;
  });
  const mx = Math.max(...counts, 1);
  const bw = w / B;
  counts.forEach((c, i) => {
    const bh = (c / mx) * (h - 16);
    ctx.fillStyle = c > 0 ? "#4f8ef7" : "#161820";
    ctx.beginPath();
    ctx.roundRect(i * bw + 2, h - bh - 8, bw - 4, bh, 3);
    ctx.fill();
  });
}

function clearData() {
  fetch("/clear").then(fetchData);
}

fetchData();
setInterval(fetchData, 2000);
</script>
</body>
</html>"""


# ----------------------------------------------------------------- main

if __name__ == "__main__":
    port_arg = sys.argv[1] if len(sys.argv) > 1 else None
    serial_port = port_arg or find_serial_port()

    if serial_port:
        t = threading.Thread(target=serial_reader, args=(serial_port,), daemon=True)
        t.start()
    else:
        print("WARNING: No serial port found. Plug in the Arduino and restart,")
        print("  or pass the port as an argument: python3 server.py /dev/tty.usbmodemXXXX")

    import socket
    local_ip = socket.gethostbyname(socket.gethostname())
    print(f"Server running on http://{local_ip}:{PORT}/")
    print("Press Ctrl+C to stop.\n")

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
