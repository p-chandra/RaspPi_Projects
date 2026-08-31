# Raspberry Pi IMAX Seat Tracker API

This project runs the server side of the IMAX Tracker Android application. The
phone submits a scan job through Tailscale, the Raspberry Pi runs Playwright
with headless Chromium, and the phone retrieves the results later. A scan keeps
running when the phone locks or disconnects.

The project reports availability only. It does not reserve seats, add tickets
to a cart, or make purchases.

## Architecture

```text
Android app
    -> Tailscale
    -> Raspberry Pi API on port 8000
    -> Playwright with headless Chromium
    -> Harkins seating pages
    -> saved in-memory job result
    -> Android completion notification
```

The separate `IMAX_Seat_Tracker` repository remains the desktop-terminal
version of the scanner. This directory owns the Raspberry Pi API deployment.

## Files

```text
IMAX_Seat_Tracker/
|-- api_server.py
|-- harkins_seat_checker.py
|-- imax-tracker-api.service
|-- requirements.txt
`-- tests/
```

## Requirements

- Raspberry Pi with a 64-bit Raspberry Pi OS based on Debian 12 or newer
- Python 3.10 or newer
- Tailscale
- Playwright and its matching Chromium build
- Internet access to the Harkins website

Confirm the operating-system architecture:

```bash
uname -m
```

The expected result is `aarch64`.

## Installation

Clone `RaspPi_Projects` under the Pi user's Documents directory so this project
is located at:

```text
/home/p-c/Documents/RaspPi_Projects/IMAX_Seat_Tracker
```

Install the base packages and Python environment:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl

cd /home/p-c/Documents/RaspPi_Projects/IMAX_Seat_Tracker
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
sudo .venv/bin/python -m playwright install-deps chromium
```

Install and connect Tailscale using its official Linux instructions, then find
the Pi's private address:

```bash
sudo systemctl enable --now tailscaled
sudo tailscale up
tailscale ip -4
```

The Android app is currently configured for:

```text
http://100.117.156.54:8000
```

## Manual API startup

```bash
cd /home/p-c/Documents/RaspPi_Projects/IMAX_Seat_Tracker
.venv/bin/python api_server.py
```

Verify it in another terminal:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status": "ok"}
```

## Start automatically with systemd

```bash
cd /home/p-c/Documents/RaspPi_Projects/IMAX_Seat_Tracker
sudo install -m 644 imax-tracker-api.service /etc/systemd/system/imax-tracker-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now imax-tracker-api.service
```

Check status and logs:

```bash
systemctl status imax-tracker-api.service --no-pager
journalctl -u imax-tracker-api.service -n 100 --no-pager
```

After changing Python code:

```bash
sudo systemctl restart imax-tracker-api.service
```

Do not run `api_server.py` manually while the systemd service is active; only
one process can listen on port 8000.

## API

### Health check

```http
GET /health
```

### Start a background scan

```http
POST /scan-jobs
Content-Type: application/json
```

Example request:

```json
{
  "start_date": "2026-08-31",
  "end_date": "2026-09-03",
  "first_row": "F",
  "last_row": "M",
  "first_seat": 10,
  "last_seat": 25
}
```

The API responds immediately with HTTP 202:

```json
{
  "job_id": "c14d1f6e5a6d4f5da4b71865d1411ab4",
  "status": "queued"
}
```

### Check a background scan

```http
GET /scan-jobs/{job_id}
```

Possible states are `queued`, `running`, `complete`, and `failed`. A completed
response contains a `results` array:

```json
{
  "job_id": "c14d1f6e5a6d4f5da4b71865d1411ab4",
  "status": "complete",
  "results": [
    {
      "date": "2026-09-01",
      "showtime": "11:45 AM",
      "seats": ["F10", "F11"]
    }
  ]
}
```

### Legacy synchronous scan

`POST /scan` remains available for diagnostics, but clients should use the job
endpoints so a dropped phone connection does not lose the response.

## Job behavior

- A single worker processes scans sequentially.
- Job state and results are currently held in memory.
- Restarting the API service clears queued, running, and completed jobs.
- The Android client treats a missing job after restart as a failed scan.
- The maximum accepted date range is 14 days.

## Tests

```bash
cd /home/p-c/Documents/RaspPi_Projects/IMAX_Seat_Tracker
.venv/bin/python -m unittest discover -s tests -v
```

## Troubleshooting

### Port 8000 is already in use

```bash
sudo ss -ltnp | grep ':8000'
```

Stop any manually launched `api_server.py`, then restart the systemd service.

### Chromium fails to launch

```bash
.venv/bin/python -m playwright install chromium
sudo .venv/bin/python -m playwright install-deps chromium
```

### A showing cannot be checked

Inspect `harkins_debug/` and the service journal. The scanner saves diagnostic
HTML, screenshots, and seat data when navigation or seat inspection fails.

### Browser profile is locked

Stop other scanner processes before restarting the service. The persistent
profile is stored in `harkins_browser_profile/`.

## Security

- Keep port 8000 private; do not configure router port forwarding.
- Restrict access through Tailscale grants or ACLs.
- The API uses HTTP inside the encrypted Tailscale tunnel.
- Do not commit credentials, Tailscale authentication keys, browser profiles,
  logs, debug captures, or virtual environments.
