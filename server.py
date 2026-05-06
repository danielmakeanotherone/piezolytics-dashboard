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
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Piezolytics</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=IBM+Plex+Mono:wght@400;500&family=Lora:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#f5f1e6;--card:#fffcf5;--fg:#4a3f35;--fg-muted:#7d6b56;
  --border:#dbd0ba;--muted:#ece5d8;--accent:#d4c8aa;
  --primary:#a67c52;--primary-dk:#8d6e4c;--primary-lt:#c0a080;
  --shadow:rgba(40,28,20,.11);
  --serif:'Libre Baskerville',Georgia,serif;
  --display:'Lora',Georgia,serif;
  --mono:'IBM Plex Mono','Courier New',monospace;
}
body{font-family:var(--serif);background:var(--bg);color:var(--fg);min-height:100vh;display:flex;flex-direction:column}

/* ── Page header ── */
.page-header{
  background:var(--primary);
  padding:28px 48px 24px;
  display:flex;align-items:flex-end;justify-content:space-between;
  box-shadow:0 2px 10px rgba(40,28,20,.22);
  position:sticky;top:0;z-index:20;
}
.wordmark{
  font-family:var(--display);font-size:clamp(48px,6vw,80px);
  font-weight:600;color:#fff;line-height:1;letter-spacing:-0.02em;
}
.wordmark em{color:rgba(255,255,255,0.55);font-style:normal}
.header-sub{font-family:var(--serif);font-style:italic;font-size:13px;color:rgba(255,255,255,0.5);margin-top:6px}
.header-right{display:flex;align-items:center;gap:12px;padding-bottom:6px}
.live-pill{
  display:flex;align-items:center;gap:7px;
  background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.2);
  border-radius:100px;padding:6px 16px;
  font-family:var(--mono);font-size:11px;color:rgba(255,255,255,0.7);
}
.live-dot{width:7px;height:7px;border-radius:50%;background:rgba(255,255,255,0.3);flex-shrink:0;transition:background .4s}
.live-dot.on{background:#fff;box-shadow:0 0 0 3px rgba(255,255,255,0.18);animation:breathe 2.5s ease-in-out infinite}
@keyframes breathe{0%,100%{box-shadow:0 0 0 3px rgba(255,255,255,0.18)}50%{box-shadow:0 0 0 7px rgba(255,255,255,0.05)}}
.btn{
  font-family:var(--serif);font-size:12px;
  background:rgba(255,255,255,0.12);color:rgba(255,255,255,0.85);
  border:1px solid rgba(255,255,255,0.22);padding:7px 18px;border-radius:4px;
  cursor:pointer;transition:background .15s;
}
.btn:hover{background:rgba(255,255,255,0.22)}

/* ── Tab nav ── */
.tab-nav{
  background:var(--primary-dk);
  display:flex;gap:0;padding:0 48px;
  border-bottom:2px solid rgba(0,0,0,.1);
}
.tab-btn{
  font-family:var(--serif);font-size:13px;color:rgba(255,255,255,0.55);
  padding:13px 22px;cursor:pointer;border:none;background:none;
  border-bottom:2px solid transparent;margin-bottom:-2px;transition:color .2s,border-color .2s;
  letter-spacing:0.01em;
}
.tab-btn:hover{color:rgba(255,255,255,0.8)}
.tab-btn.active{color:#fff;border-bottom-color:#fff;font-weight:700}

/* ── Panes ── */
.pane{display:none;flex:1;flex-direction:column}
.pane.active{display:flex}

/* ── Stats row ── */
.stats-row{
  background:var(--card);border-bottom:1px solid var(--border);
  padding:0 48px;display:flex;align-items:stretch;
  box-shadow:0 1px 4px var(--shadow);
}
.stat-item{
  display:flex;flex-direction:column;justify-content:center;
  padding:18px 36px 16px 0;gap:4px;
}
.stat-item+.stat-item{border-left:1px solid var(--border);padding-left:36px}
.stat-val{font-family:var(--mono);font-size:28px;font-weight:500;color:var(--fg);line-height:1}
.stat-lbl{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--fg-muted)}
.stat-updated{margin-left:auto;font-family:var(--mono);font-size:10px;color:var(--accent);align-self:center}

/* ── Hero ── */
.ov-hero{
  flex:1;display:grid;grid-template-columns:1fr 1.5fr;gap:0;
  min-height:0;overflow:hidden;
}

/* Feed panel */
.feed-panel{
  border-right:1px solid var(--border);
  display:flex;flex-direction:column;overflow:hidden;
}
.panel-head{
  padding:18px 24px 14px;border-bottom:1px solid var(--border);
  font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.14em;color:var(--accent);
  flex-shrink:0;
}
.feed-list{flex:1;overflow-y:auto;padding:8px 0}
.feed-item{
  display:flex;align-items:center;gap:14px;
  padding:10px 24px;border-bottom:1px solid var(--muted);
  animation:fadeSlide .35s ease;
}
@keyframes fadeSlide{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}
.feed-item:last-child{border-bottom:none}
.feed-dot{
  width:34px;height:34px;border-radius:50%;flex-shrink:0;
  background:var(--muted);border:2px solid var(--border);
  display:flex;align-items:center;justify-content:center;
  font-family:var(--mono);font-size:10px;color:var(--fg-muted);font-weight:500;
}
.feed-dot.fresh{background:var(--primary);border-color:var(--primary-dk);color:#fff}
.feed-info{flex:1;min-width:0}
.feed-tile{font-family:var(--mono);font-size:12px;font-weight:500;color:var(--fg)}
.feed-meta{font-size:11px;color:var(--fg-muted);margin-top:2px}
.feed-val{font-family:var(--mono);font-size:13px;color:var(--primary);font-weight:500;flex-shrink:0}
.feed-empty{padding:48px 24px;text-align:center;font-style:italic;color:var(--accent);font-size:13px}

/* 3-D stage */
.stage-panel{
  background:linear-gradient(160deg,#2a1f14 0%,#1a110a 100%);
  display:flex;flex-direction:column;overflow:hidden;
}
.stage-head{
  padding:18px 28px 14px;border-bottom:1px solid rgba(255,255,255,.06);
  font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.14em;color:rgba(255,255,255,.3);
  flex-shrink:0;display:flex;align-items:center;justify-content:space-between;
}
.stage-head-r{font-family:var(--mono);font-size:10px;color:rgba(255,255,255,.18)}
.stage-wrap{flex:1;display:flex;align-items:center;justify-content:center;padding:20px 28px 32px;min-height:0}
.stage-persp{perspective:700px;perspective-origin:50% 30%}
.stage-floor{
  width:340px;
  display:grid;gap:14px;padding:28px;
  background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);border-radius:8px;
  transform:rotateX(48deg);transform-style:preserve-3d;
  box-shadow:0 40px 80px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.06);
}

/* 3-D tile */
.t3d{
  position:relative;height:70px;border-radius:6px;
  background:linear-gradient(135deg,rgba(166,124,82,.18),rgba(166,124,82,.08));
  border:1px solid rgba(166,124,82,.25);
  display:flex;align-items:center;justify-content:center;
  cursor:default;transition:transform .12s ease,background .2s ease,box-shadow .2s ease;
  transform-style:preserve-3d;
  box-shadow:0 4px 12px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.06);
}
.t3d .t3d-label{
  font-family:var(--mono);font-size:11px;color:rgba(255,255,255,.35);
  font-weight:500;letter-spacing:.08em;z-index:1;
}
.t3d .t3d-count{
  position:absolute;top:6px;right:9px;
  font-family:var(--mono);font-size:9px;color:rgba(255,255,255,.2);
}
.t3d.pressing{
  transform:translateY(4px) scaleX(0.97);
  background:linear-gradient(135deg,rgba(166,124,82,.55),rgba(192,160,128,.35));
  border-color:rgba(166,124,82,.7);
  box-shadow:0 1px 4px rgba(0,0,0,.5),0 0 18px rgba(166,124,82,.22),inset 0 1px 0 rgba(255,255,255,.1);
}
.t3d.pressing .t3d-label{color:rgba(255,255,255,.85)}

/* ripple rings */
.ripple-ring{
  position:absolute;border-radius:50%;
  border:2px solid rgba(166,124,82,.7);
  pointer-events:none;z-index:2;
  animation:ripple .8s ease-out forwards;
}
@keyframes ripple{
  0%  {width:10px;height:10px;top:50%;left:50%;margin:-5px 0 0 -5px;opacity:.9}
  100%{width:110px;height:110px;top:50%;left:50%;margin:-55px 0 0 -55px;opacity:0}
}

/* ── Zones pane ── */
.zones-wrap{padding:32px 48px 48px;flex:1}
.zones-wrap h2{font-family:var(--display);font-size:22px;font-weight:600;color:var(--fg);margin-bottom:6px}
.zones-sub{font-style:italic;color:var(--fg-muted);font-size:13px;margin-bottom:26px}
.zones-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:22px}
.zones-empty{
  grid-column:1/-1;padding:64px 32px;text-align:center;
  font-style:italic;color:var(--accent);font-size:14px;
  background:var(--card);border:1px solid var(--border);border-radius:6px;
}

/* Zone card */
.zcard{background:var(--card);border:1px solid var(--border);border-radius:6px;box-shadow:2px 3px 8px var(--shadow);overflow:hidden}
.zcard-top{
  padding:16px 20px 14px;display:flex;align-items:center;
  justify-content:space-between;border-bottom:1px solid var(--muted);
}
.zcard-eyebrow{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.14em;color:var(--fg-muted)}
.zcard-title{font-family:var(--display);font-size:18px;font-weight:600;color:var(--fg);margin-top:3px}
.zcard-status{display:flex;align-items:center;gap:6px;font-family:var(--mono);font-size:10px;color:var(--fg-muted)}
.zdot{width:7px;height:7px;border-radius:50%;background:var(--accent);transition:background .4s}
.zdot.on{background:var(--primary);box-shadow:0 0 0 3px rgba(166,124,82,.2);animation:breathe 2.5s ease-in-out infinite}
.zcard-body{padding:18px 20px 14px}
.zbig-row{display:flex;align-items:flex-end;gap:28px;margin-bottom:16px}
.zbig-num{font-family:var(--mono);font-size:54px;font-weight:500;line-height:1;color:var(--fg);letter-spacing:-.03em}
.zbig-lbl{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--fg-muted);margin-top:5px}
.zside{display:flex;flex-direction:column;gap:11px;padding-bottom:4px}
.zside-val{font-family:var(--mono);font-size:15px;font-weight:500;color:var(--fg);line-height:1}
.zside-lbl{font-size:10px;text-transform:uppercase;letter-spacing:.09em;color:var(--fg-muted);margin-top:2px}
.chart-eye{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--accent);margin-bottom:7px}
canvas{width:100%;display:block}
.zcard-table{border-top:1px solid var(--muted)}
table{width:100%;border-collapse:collapse}
th{padding:10px 20px 8px;text-align:left;font-family:var(--mono);font-size:10px;font-weight:400;text-transform:uppercase;letter-spacing:.09em;color:var(--accent);border-bottom:1px solid var(--border)}
td{padding:8px 20px;font-family:var(--mono);font-size:12px;color:var(--fg-muted);border-bottom:1px solid var(--muted)}
tr:last-child td{border-bottom:none}
td.num{color:var(--fg)}
.badge{display:inline-block;padding:2px 8px;border-radius:3px;font-family:var(--mono);font-size:10px;font-weight:500;letter-spacing:.04em}
.badge.ab{background:#f0ebe0;color:var(--primary);border:1px solid var(--border)}
.badge.ba{background:#e8e0d4;color:#7a5c3a;border:1px solid #d0c4b0}
.empty-row td{text-align:center;font-style:italic;color:var(--accent);padding:22px;border:none}
</style>
</head>
<body>

<!-- ═══════════════════ PAGE HEADER ═══════════════════ -->
<header class="page-header">
  <div>
    <div class="wordmark">Piezo<em>lytics</em></div>
    <div class="header-sub">Live floor sensor analytics</div>
  </div>
  <div class="header-right">
    <div class="live-pill">
      <div class="live-dot" id="live-dot"></div>
      <span id="live-text">connecting</span>
    </div>
    <button class="btn" onclick="clearData()">Clear data</button>
    <button class="btn" onclick="fetchData()">Refresh</button>
  </div>
</header>

<!-- ═══════════════════ TAB NAV ═══════════════════ -->
<nav class="tab-nav">
  <button class="tab-btn active" onclick="showTab('overview',this)">Live Overview</button>
  <button class="tab-btn"        onclick="showTab('zones',this)">Tile Zones</button>
</nav>

<!-- ═══════════════════ OVERVIEW PANE ═══════════════════ -->
<div class="pane active" id="pane-overview">

  <!-- stats row -->
  <div class="stats-row">
    <div class="stat-item">
      <div class="stat-val" id="s-total">—</div>
      <div class="stat-lbl">Total visits</div>
    </div>
    <div class="stat-item">
      <div class="stat-val" id="s-tiles">—</div>
      <div class="stat-lbl">Active tiles</div>
    </div>
    <div class="stat-item">
      <div class="stat-val" id="s-top">—</div>
      <div class="stat-lbl">Most active</div>
    </div>
    <div class="stat-item">
      <div class="stat-val" id="s-last">—</div>
      <div class="stat-lbl">Last event</div>
    </div>
    <div class="stat-updated" id="s-time"></div>
  </div>

  <!-- hero -->
  <div class="ov-hero">

    <!-- live feed -->
    <div class="feed-panel">
      <div class="panel-head">Live event feed</div>
      <div class="feed-list" id="feed-list">
        <div class="feed-empty" id="feed-empty">Waiting for sensor events…</div>
      </div>
    </div>

    <!-- 3-D stage -->
    <div class="stage-panel">
      <div class="stage-head">
        <span>Building floor plan</span>
        <span class="stage-head-r" id="stage-tile-count">0 tiles</span>
      </div>
      <div class="stage-wrap">
        <div class="stage-persp">
          <div class="stage-floor" id="stage-floor">
            <!-- tiles injected dynamically -->
          </div>
        </div>
      </div>
    </div>

  </div>
</div><!-- /pane-overview -->

<!-- ═══════════════════ ZONES PANE ═══════════════════ -->
<div class="pane" id="pane-zones">
  <div class="zones-wrap">
    <h2>Tile Zones</h2>
    <div class="zones-sub">Each zone appears automatically when sensor data arrives.</div>
    <div class="zones-grid" id="zones-grid">
      <div class="zones-empty" id="zones-empty">No tile data yet — step on a sensor to begin.</div>
    </div>
  </div>
</div><!-- /pane-zones -->

<script>
// ── state ─────────────────────────────────────────────────────────────
const tileMap   = {};   // tile_id → { label, num, visits[] }
const feedItems = [];
let   prevTotal = 0;

// ── tab switching ──────────────────────────────────────────────────────
function showTab(name, btn) {
  document.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('pane-' + name).classList.add('active');
  btn.classList.add('active');
}

// ── dynamic tile discovery ─────────────────────────────────────────────
function tileLabel(id) {
  const n = id.replace(/[^0-9]/g,'') || '?';
  return { label: 'Tile ' + n, num: n.padStart(2,'0') };
}

function ensureTile(id) {
  if (tileMap[id]) return;
  const { label, num } = tileLabel(id);
  tileMap[id] = { label, num, visits: [] };
  addStage3D(id, label, num);
  addZoneCard(id, label, num);
  updateStageCount();
}

// ── 3-D stage ──────────────────────────────────────────────────────────
function addStage3D(id, label, num) {
  const floor = document.getElementById('stage-floor');
  // recalculate grid cols based on tile count
  const tileCount = Object.keys(tileMap).length;
  const cols = tileCount <= 2 ? 1 : tileCount <= 4 ? 2 : 3;
  floor.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  floor.style.width = cols === 1 ? '220px' : cols === 2 ? '310px' : '420px';

  const div = document.createElement('div');
  div.className = 't3d';
  div.id = 't3d-' + id;
  div.innerHTML = `<span class="t3d-label">${label}</span><span class="t3d-count" id="t3d-cnt-${id}">0</span>`;
  floor.appendChild(div);
}

function updateStageCount() {
  const n = Object.keys(tileMap).length;
  document.getElementById('stage-tile-count').textContent = n + (n === 1 ? ' tile' : ' tiles');
}

function pressTile(id) {
  const el = document.getElementById('t3d-' + id);
  if (!el) return;
  el.classList.add('pressing');
  // ripple
  const ring = document.createElement('div');
  ring.className = 'ripple-ring';
  el.appendChild(ring);
  ring.addEventListener('animationend', () => ring.remove());
  setTimeout(() => el.classList.remove('pressing'), 400);
}

// ── zone cards ─────────────────────────────────────────────────────────
function addZoneCard(id, label, num) {
  document.getElementById('zones-empty')?.remove();
  const safeId = id.replace(/[^a-z0-9]/gi,'');
  const grid = document.getElementById('zones-grid');
  const card = document.createElement('div');
  card.className = 'zcard';
  card.id = 'zcard-' + safeId;
  card.innerHTML = `
  <div class="zcard-top">
    <div>
      <div class="zcard-eyebrow">Sensor ${num}</div>
      <div class="zcard-title">${label}</div>
    </div>
    <div class="zcard-status">
      <div class="zdot" id="zdot-${safeId}"></div>
      <span id="ztime-${safeId}">no data</span>
    </div>
  </div>
  <div class="zcard-body">
    <div class="zbig-row">
      <div>
        <div class="zbig-num" id="zn-${safeId}">—</div>
        <div class="zbig-lbl">visits</div>
      </div>
      <div class="zside">
        <div>
          <div class="zside-val" id="zpeak-${safeId}">—</div>
          <div class="zside-lbl">Avg peak A</div>
        </div>
        <div>
          <div class="zside-val" id="zlast-${safeId}">—</div>
          <div class="zside-lbl">Last visit</div>
        </div>
      </div>
    </div>
    <div class="chart-eye">Activity</div>
    <canvas id="zc-${safeId}" height="52"></canvas>
  </div>
  <div class="zcard-table">
    <table>
      <thead><tr><th>Time</th><th>Order</th><th>Peak A</th><th>Dwell</th></tr></thead>
      <tbody id="ztb-${safeId}"></tbody>
    </table>
  </div>`;
  grid.appendChild(card);
}

// ── feed ───────────────────────────────────────────────────────────────
function pushFeed(v) {
  document.getElementById('feed-empty')?.remove();
  const list = document.getElementById('feed-list');
  const info = tileMap[v.tile_id];
  const label = info ? info.label : v.tile_id;
  const time  = (v.ts||'').split(' ')[1] || '—';
  const peak  = v.tile_a_peak ?? '—';
  const item  = document.createElement('div');
  item.className = 'feed-item';
  item.innerHTML = `
    <div class="feed-dot fresh">${info ? info.num : '?'}</div>
    <div class="feed-info">
      <div class="feed-tile">${label}</div>
      <div class="feed-meta">${time} · peak ${peak}</div>
    </div>
    <div class="feed-val">${peak}</div>`;
  list.prepend(item);
  feedItems.unshift(item);
  if (feedItems.length > 40) feedItems.pop().remove();
  // fade older dots
  setTimeout(() => item.querySelector('.feed-dot').classList.remove('fresh'), 3000);
}

// ── sparkline ─────────────────────────────────────────────────────────
function drawSparkline(canvas, visits) {
  canvas.width  = canvas.offsetWidth || 320;
  canvas.height = 52;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0,0,w,h);
  if (!visits.length) {
    ctx.fillStyle = '#d4c8aa';
    ctx.font = "11px 'IBM Plex Mono',monospace";
    ctx.textAlign = 'center';
    ctx.fillText('no activity yet', w/2, h/2+4);
    return;
  }
  const t0   = visits[0].epoch;
  const tEnd = visits[visits.length-1].epoch;
  const span = Math.max(tEnd-t0, 60);
  const B    = 24;
  const counts = Array(B).fill(0);
  visits.forEach(v => { counts[Math.min(Math.floor((v.epoch-t0)/(span/B)), B-1)]++; });
  const mx = Math.max(...counts, 1);
  const bw = w/B;
  counts.forEach((c,i) => {
    const bh = Math.max((c/mx)*(h-6), c>0?3:0);
    if (c===0) {
      ctx.fillStyle = '#ece5d8';
      ctx.fillRect(i*bw+2, h-3, bw-4, 2);
    } else {
      const g = ctx.createLinearGradient(0,h-bh-3,0,h-3);
      g.addColorStop(0,'#a67c52'); g.addColorStop(1,'#c9a97a');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.roundRect(i*bw+2, h-bh-3, bw-4, bh, 2);
      ctx.fill();
    }
  });
}

// ── render zone card ───────────────────────────────────────────────────
function renderZone(id) {
  const info    = tileMap[id];
  const visits  = info.visits;
  const safeId  = id.replace(/[^a-z0-9]/gi,'');
  const total   = visits.length;
  const zdot    = document.getElementById('zdot-'+safeId);
  const ztime   = document.getElementById('ztime-'+safeId);
  if (!zdot) return;
  if (total > 0) {
    zdot.classList.add('on');
    ztime.textContent = (visits[visits.length-1].ts||'').split(' ')[1] || '—';
  } else {
    zdot.classList.remove('on');
    ztime.textContent = 'no data';
  }
  const avgPeak  = total ? Math.round(visits.reduce((s,v)=>s+(v.tile_a_peak||0),0)/total) : '—';
  const lastTime = total ? ((visits[visits.length-1].ts||'').split(' ')[1]||'—') : '—';
  document.getElementById('zn-'+safeId).textContent    = total || '—';
  document.getElementById('zpeak-'+safeId).textContent = avgPeak;
  document.getElementById('zlast-'+safeId).textContent = lastTime;
  drawSparkline(document.getElementById('zc-'+safeId), visits);
  const tbody  = document.getElementById('ztb-'+safeId);
  const recent = [...visits].reverse().slice(0,6);
  if (!recent.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="4">No visits yet</td></tr>';
    return;
  }
  tbody.innerHTML = recent.map(v=>`<tr>
    <td>${(v.ts||'').split(' ')[1]||'—'}</td>
    <td>${v.first_tile===1
      ?'<span class="badge ab">A → B</span>'
      :'<span class="badge ba">B → A</span>'}</td>
    <td class="num">${v.tile_a_peak??'—'}</td>
    <td class="num">${v.tile_a_dwell_ms??'—'}ms</td>
  </tr>`).join('');
}

// ── main fetch & update ────────────────────────────────────────────────
function fetchData() {
  fetch('/data')
    .then(r => r.json())
    .then(rows => {
      const visits = rows.filter(r => r.event_type === 'VISIT');

      // discover & seed tiles
      visits.forEach(v => {
        ensureTile(v.tile_id);
        tileMap[v.tile_id].visits = visits.filter(x => x.tile_id === v.tile_id);
      });

      // detect new visits since last poll
      if (visits.length > prevTotal) {
        const newOnes = visits.slice(prevTotal);
        newOnes.forEach(v => {
          pushFeed(v);
          pressTile(v.tile_id);
        });
      }
      prevTotal = visits.length;

      // 3-D stage counts
      Object.keys(tileMap).forEach(id => {
        const cnt = document.getElementById('t3d-cnt-'+id);
        if (cnt) cnt.textContent = tileMap[id].visits.length;
      });

      // zone cards
      Object.keys(tileMap).forEach(renderZone);

      // global stats
      const activeTiles = Object.values(tileMap).filter(t=>t.visits.length>0).length;
      const totals      = Object.entries(tileMap).map(([id,t])=>({id,n:t.visits.length}));
      const top         = totals.sort((a,b)=>b.n-a.n)[0];
      const lastVisit   = visits.length ? (visits[visits.length-1].ts||'').split(' ')[1]||'—' : '—';
      document.getElementById('s-total').textContent = visits.length || '—';
      document.getElementById('s-tiles').textContent = activeTiles  || '—';
      document.getElementById('s-top').textContent   = top && top.n>0 ? tileMap[top.id].label : '—';
      document.getElementById('s-last').textContent  = lastVisit;
      document.getElementById('s-time').textContent  =
        'updated ' + new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'});

      const dot = document.getElementById('live-dot');
      const txt = document.getElementById('live-text');
      if (visits.length > 0) { dot.classList.add('on'); txt.textContent = 'live'; }
      else { dot.classList.remove('on'); txt.textContent = 'no data'; }
    })
    .catch(() => {
      document.getElementById('live-text').textContent = 'error';
      document.getElementById('live-dot').style.background = 'rgba(255,80,60,.7)';
    });
}

function clearData() { fetch('/clear').then(fetchData); }
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
