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
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Piezolytics</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=IBM+Plex+Mono:wght@400;500&family=Lora:ital,wght@0,600;1,400&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg:         #f5f1e6;
  --card:       #fffcf5;
  --fg:         #4a3f35;
  --fg-muted:   #7d6b56;
  --border:     #dbd0ba;
  --muted:      #ece5d8;
  --accent:     #d4c8aa;
  --primary:    #a67c52;
  --primary-lt: #c0a080;
  --shadow:     rgba(40,28,20,0.11);
  --serif:      'Libre Baskerville', Georgia, serif;
  --display:    'Lora', Georgia, serif;
  --mono:       'IBM Plex Mono', 'Courier New', monospace;
}
body { font-family: var(--serif); background: var(--bg); color: var(--fg); min-height: 100vh; }

/* Header */
.header {
  background: var(--card);
  border-bottom: 1px solid var(--border);
  padding: 18px 36px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 1px 4px var(--shadow);
  position: sticky; top: 0; z-index: 10;
}
.logo { font-family: var(--display); font-size: 22px; font-weight: 600; color: var(--fg); letter-spacing: -0.01em; }
.logo em { color: var(--primary); font-style: normal; }
.tagline { font-family: var(--serif); font-style: italic; font-size: 12px; color: var(--fg-muted); margin-top: 2px; }
.header-right { display: flex; align-items: center; gap: 12px; }
.live-pill {
  display: flex; align-items: center; gap: 7px;
  background: var(--muted); border: 1px solid var(--border);
  border-radius: 100px; padding: 5px 14px;
  font-family: var(--mono); font-size: 11px; color: var(--fg-muted);
}
.live-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--accent); flex-shrink: 0; transition: background 0.4s;
}
.live-dot.on { background: var(--primary); box-shadow: 0 0 0 3px rgba(166,124,82,0.18); animation: breathe 2.5s ease-in-out infinite; }
@keyframes breathe {
  0%,100% { box-shadow: 0 0 0 3px rgba(166,124,82,0.18); }
  50%      { box-shadow: 0 0 0 6px rgba(166,124,82,0.06); }
}
.btn {
  font-family: var(--serif); font-size: 12px;
  background: var(--card); color: var(--fg-muted);
  border: 1px solid var(--border); padding: 7px 16px; border-radius: 4px;
  cursor: pointer; box-shadow: 1px 2px 3px var(--shadow); transition: background 0.15s, color 0.15s;
}
.btn:hover { background: var(--muted); color: var(--fg); }

/* Summary bar */
.summary {
  background: var(--primary);
  padding: 0 36px;
  display: flex; align-items: stretch;
}
.sum-item {
  display: flex; flex-direction: column; justify-content: center;
  padding: 13px 32px 13px 0; gap: 3px;
}
.sum-item + .sum-item { border-left: 1px solid rgba(255,255,255,0.2); padding-left: 32px; }
.sum-val { font-family: var(--mono); font-size: 20px; font-weight: 500; color: #fff; line-height: 1; }
.sum-lbl { font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: rgba(255,255,255,0.55); }
.sum-updated { margin-left: auto; font-family: var(--mono); font-size: 10px; color: rgba(255,255,255,0.35); align-self: center; }

/* Grid */
.content { padding: 28px 36px 48px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }

/* Card */
.tile-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 6px; box-shadow: 2px 3px 6px var(--shadow);
  overflow: hidden; display: flex; flex-direction: column;
}
.card-top {
  padding: 15px 20px 13px; display: flex; align-items: center;
  justify-content: space-between; border-bottom: 1px solid var(--muted);
}
.tile-eyebrow { font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.14em; color: var(--fg-muted); }
.tile-title { font-family: var(--display); font-size: 17px; font-weight: 600; color: var(--fg); margin-top: 2px; }
.tile-status { display: flex; align-items: center; gap: 6px; font-family: var(--mono); font-size: 10px; color: var(--fg-muted); }
.tdot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); transition: background 0.4s; }
.tdot.on { background: var(--primary); box-shadow: 0 0 0 2px rgba(166,124,82,0.2); animation: breathe 2.5s ease-in-out infinite; }

/* Body */
.card-body { padding: 18px 20px 14px; }
.big-row { display: flex; align-items: flex-end; gap: 28px; margin-bottom: 16px; }
.big-num { font-family: var(--mono); font-size: 58px; font-weight: 500; line-height: 1; color: var(--fg); letter-spacing: -0.03em; }
.big-lbl { font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; color: var(--fg-muted); margin-top: 5px; }
.side-stats { display: flex; flex-direction: column; gap: 11px; padding-bottom: 4px; }
.side-val { font-family: var(--mono); font-size: 15px; font-weight: 500; color: var(--fg); line-height: 1; }
.side-lbl { font-size: 10px; text-transform: uppercase; letter-spacing: 0.09em; color: var(--fg-muted); margin-top: 2px; }

/* Chart */
.chart-eyebrow { font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--accent); margin-bottom: 7px; }
canvas { width: 100%; display: block; }

/* Table */
.card-table { border-top: 1px solid var(--muted); }
table { width: 100%; border-collapse: collapse; }
th {
  padding: 10px 20px 8px; text-align: left;
  font-family: var(--mono); font-size: 10px; font-weight: 400;
  text-transform: uppercase; letter-spacing: 0.09em;
  color: var(--accent); border-bottom: 1px solid var(--border);
}
td { padding: 8px 20px; font-family: var(--mono); font-size: 12px; color: var(--fg-muted); border-bottom: 1px solid var(--muted); }
tr:last-child td { border-bottom: none; }
td.num { color: var(--fg); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 3px; font-family: var(--mono); font-size: 10px; font-weight: 500; letter-spacing: 0.04em; }
.badge.ab { background: #f0ebe0; color: var(--primary); border: 1px solid var(--border); }
.badge.ba { background: #e8e0d4; color: #7a5c3a; border: 1px solid #d0c4b0; }
.empty-row td { text-align: center; font-style: italic; color: var(--accent); padding: 22px; border: none; }
</style>
</head>
<body>

<header class="header">
  <div>
    <div class="logo">Piezo<em>lytics</em></div>
    <div class="tagline">Live floor sensor analytics</div>
  </div>
  <div class="header-right">
    <div class="live-pill">
      <div class="live-dot" id="live-dot"></div>
      <span id="live-text">connecting</span>
    </div>
    <button class="btn" onclick="clearData()">Clear</button>
    <button class="btn" onclick="fetchData()">Refresh</button>
  </div>
</header>

<div class="summary">
  <div class="sum-item">
    <div class="sum-val" id="s-total">—</div>
    <div class="sum-lbl">Total visits</div>
  </div>
  <div class="sum-item">
    <div class="sum-val" id="s-tiles">—</div>
    <div class="sum-lbl">Active tiles</div>
  </div>
  <div class="sum-item">
    <div class="sum-val" id="s-top">—</div>
    <div class="sum-lbl">Most active</div>
  </div>
  <div class="sum-updated" id="s-time"></div>
</div>

<div class="content">
  <div class="grid" id="grid"></div>
</div>

<script>
const TILES = [
  { key: "tile_1", label: "Tile 1", n: "01" },
  { key: "tile_2", label: "Tile 2", n: "02" },
  { key: "tile_3", label: "Tile 3", n: "03" },
  { key: "tile_4", label: "Tile 4", n: "04" },
];

TILES.forEach(t => {
  const id = t.key.replace("_","");
  document.getElementById("grid").innerHTML += `
  <div class="tile-card">
    <div class="card-top">
      <div>
        <div class="tile-eyebrow">Sensor ${t.n}</div>
        <div class="tile-title">${t.label}</div>
      </div>
      <div class="tile-status">
        <div class="tdot" id="tdot-${id}"></div>
        <span id="ttime-${id}">no data</span>
      </div>
    </div>
    <div class="card-body">
      <div class="big-row">
        <div>
          <div class="big-num" id="${id}-total">—</div>
          <div class="big-lbl">visits</div>
        </div>
        <div class="side-stats">
          <div>
            <div class="side-val" id="${id}-peak">—</div>
            <div class="side-lbl">Avg peak A</div>
          </div>
          <div>
            <div class="side-val" id="${id}-last">—</div>
            <div class="side-lbl">Last visit</div>
          </div>
        </div>
      </div>
      <div class="chart-eyebrow">Activity</div>
      <canvas id="c-${id}" height="52"></canvas>
    </div>
    <div class="card-table">
      <table>
        <thead><tr><th>Time</th><th>Order</th><th>Peak A</th><th>Dwell A</th></tr></thead>
        <tbody id="tb-${id}"></tbody>
      </table>
    </div>
  </div>`;
});

function fetchData() {
  fetch("/data")
    .then(r => r.json())
    .then(rows => {
      const visits = rows.filter(r => r.event_type === "VISIT");
      TILES.forEach(t => renderTile(t, visits.filter(v => v.tile_id === t.key)));

      const counts  = TILES.map(t => visits.filter(v => v.tile_id === t.key).length);
      const active  = counts.filter(c => c > 0).length;
      const topIdx  = counts.indexOf(Math.max(...counts));
      const topLbl  = counts[topIdx] > 0 ? TILES[topIdx].label : "—";

      document.getElementById("s-total").textContent = visits.length || "—";
      document.getElementById("s-tiles").textContent = active || "—";
      document.getElementById("s-top").textContent   = topLbl;
      document.getElementById("s-time").textContent  =
        "updated " + new Date().toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",second:"2-digit"});

      const dot = document.getElementById("live-dot");
      const txt = document.getElementById("live-text");
      if (visits.length > 0) { dot.classList.add("on"); txt.textContent = "live"; }
      else { dot.classList.remove("on"); txt.textContent = "no data"; }
    })
    .catch(() => {
      document.getElementById("live-text").textContent = "error";
      document.getElementById("live-dot").style.background = "#b54a35";
    });
}

function renderTile(t, visits) {
  const id    = t.key.replace("_","");
  const total = visits.length;
  const tdot  = document.getElementById("tdot-"+id);
  const ttime = document.getElementById("ttime-"+id);

  if (total > 0) {
    tdot.classList.add("on");
    ttime.textContent = (visits[visits.length-1].ts||"").split(" ")[1] || "—";
  } else {
    tdot.classList.remove("on");
    ttime.textContent = "no data";
  }

  const avgPeak = total
    ? Math.round(visits.reduce((s,v) => s+(v.tile_a_peak||0), 0) / total) : "—";
  const lastTime = total ? ((visits[visits.length-1].ts||"").split(" ")[1]||"—") : "—";

  document.getElementById(id+"-total").textContent = total || "—";
  document.getElementById(id+"-peak").textContent  = avgPeak;
  document.getElementById(id+"-last").textContent  = lastTime;

  drawSparkline(document.getElementById("c-"+id), visits);

  const tbody  = document.getElementById("tb-"+id);
  const recent = [...visits].reverse().slice(0,6);
  if (!recent.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="4">No visits yet</td></tr>';
    return;
  }
  tbody.innerHTML = recent.map(v => `<tr>
    <td>${(v.ts||"").split(" ")[1]||"—"}</td>
    <td>${v.first_tile===1
      ? '<span class="badge ab">A → B</span>'
      : '<span class="badge ba">B → A</span>'}</td>
    <td class="num">${v.tile_a_peak??"—"}</td>
    <td class="num">${v.tile_a_dwell_ms???"—"}ms</td>
  </tr>`).join("");
}

function drawSparkline(canvas, visits) {
  canvas.width  = canvas.offsetWidth || 400;
  canvas.height = 52;
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0,0,w,h);

  if (!visits.length) {
    ctx.fillStyle = "#d4c8aa";
    ctx.font = "11px 'IBM Plex Mono',monospace";
    ctx.textAlign = "center";
    ctx.fillText("no activity yet", w/2, h/2+4);
    return;
  }

  const t0   = visits[0].epoch;
  const tEnd = visits[visits.length-1].epoch;
  const span = Math.max(tEnd-t0, 60);
  const B    = 24;
  const counts = Array(B).fill(0);
  visits.forEach(v => { counts[Math.min(Math.floor((v.epoch-t0)/(span/B)),B-1)]++; });
  const mx = Math.max(...counts,1);
  const bw = w/B;
  counts.forEach((c,i) => {
    const bh = Math.max((c/mx)*(h-6), c>0?3:0);
    if (c===0) {
      ctx.fillStyle = "#ece5d8";
      ctx.fillRect(i*bw+2, h-3, bw-4, 2);
    } else {
      const g = ctx.createLinearGradient(0,h-bh-3,0,h-3);
      g.addColorStop(0,"#a67c52"); g.addColorStop(1,"#c9a97a");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.roundRect(i*bw+2, h-bh-3, bw-4, bh, 2);
      ctx.fill();
    }
  });
}

function clearData() { fetch("/clear").then(fetchData); }
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
