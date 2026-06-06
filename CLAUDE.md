# Piezo Serial Dashboard

## What this is
Arduino Nano reads piezo sensor(s) over USB Serial → Python server stores readings → live web dashboard.

## Files
- `server.py` — HTTP server + serial reader, run with `python3 server.py`
- `nano_client.ino` — Arduino sketch to flash onto the Nano

## Dependencies
```bash
pip3 install pyserial websockets
```

## Hardware
- Piezo wired to A0 and GND
- Add 1MΩ resistor between A0 and GND to bleed charge (prevents floating reads)
- Connect Nano to Mac via USB

## How to run
```bash
python3 ~/Downloads/CLAUDE/esp32_server/server.py
# or specify port explicitly:
python3 ~/Downloads/CLAUDE/esp32_server/server.py /dev/tty.usbmodem14101
```

Dashboard: http://localhost:8080/

## API
- `GET  /`      — live dashboard with waveform chart, auto-refreshes every 2s
- `GET  /data`  — all stored readings as JSON (up to 200)
- `GET  /clear` — wipe stored data

## Sketch settings
- Sample rate: 50ms (20 Hz) — change `INTERVAL` in nano_client.ino
- Baud rate: 115200 — must match `BAUD_RATE` in server.py
- Analog pin: A0 — change `PIEZO_PIN` in nano_client.ino
