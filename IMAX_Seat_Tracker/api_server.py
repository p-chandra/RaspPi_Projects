"""Tailscale HTTP API for the IMAX Tracker Android application."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import harkins_seat_checker as checker


HOST = os.environ.get("IMAX_API_HOST", "100.117.156.54")
PORT = 8000
MAX_SCAN_DAYS = 14
MAX_REQUEST_BYTES = 16_384
REQUEST_TIMEOUT_SECONDS = 15
SCAN_JOBS: dict[str, dict[str, Any]] = {}
SCAN_JOBS_LOCK = threading.Lock()
SCAN_EXECUTION_LOCK = threading.Lock()
SCAN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="imax-scan")


class ApiError(ValueError):
    pass


class ScanBusyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanRequest:
    start_day: date
    end_day: date
    first_row: str
    last_row: str
    first_seat: int
    last_seat: int


def parse_scan_request(payload: dict[str, Any]) -> ScanRequest:
    """Validate settings without changing a scan already in progress."""
    try:
        start_day = date.fromisoformat(str(payload["start_date"]))
        end_day = date.fromisoformat(str(payload["end_date"]))
        first_row = str(payload["first_row"]).upper()
        last_row = str(payload["last_row"]).upper()
        first_seat = int(payload["first_seat"])
        last_seat = int(payload["last_seat"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ApiError("Invalid or missing scan settings") from exc

    if end_day < start_day:
        raise ApiError("End date must not be before start date")
    if (end_day - start_day).days + 1 > MAX_SCAN_DAYS:
        raise ApiError(f"Date range cannot exceed {MAX_SCAN_DAYS} days")
    if not (len(first_row) == len(last_row) == 1 and "A" <= first_row <= last_row <= "Z"):
        raise ApiError("Invalid row range")
    if not (1 <= first_seat <= last_seat <= 100):
        raise ApiError("Invalid seat-number range")
    return ScanRequest(start_day, end_day, first_row, last_row, first_seat, last_seat)


def execute_scan(settings: ScanRequest, *, blocking=True, started=None) -> list[dict[str, object]]:
    """Serialize the shared browser profile and filters across both API styles."""
    if not SCAN_EXECUTION_LOCK.acquire(blocking=blocking):
        raise ScanBusyError("Another scan is already running. Try again when it finishes.")
    previous = (checker.ALLOWED_ROWS, checker.MIN_SEAT_NUMBER, checker.MAX_SEAT_NUMBER, checker.HEADLESS)
    try:
        checker.ALLOWED_ROWS = {chr(row) for row in range(ord(settings.first_row), ord(settings.last_row) + 1)}
        checker.MIN_SEAT_NUMBER = settings.first_seat
        checker.MAX_SEAT_NUMBER = settings.last_seat
        checker.HEADLESS = True
        if started is not None:
            started()
        return checker.scan_availability(settings.start_day, settings.end_day)
    finally:
        checker.ALLOWED_ROWS, checker.MIN_SEAT_NUMBER, checker.MAX_SEAT_NUMBER, checker.HEADLESS = previous
        SCAN_EXECUTION_LOCK.release()


def update_scan_job(job_id: str, **updates: Any) -> None:
    with SCAN_JOBS_LOCK:
        job = SCAN_JOBS.get(job_id)
        if job is not None:
            job.update(updates)


def run_scan_job(job_id: str, settings: ScanRequest) -> None:
    try:
        results = execute_scan(settings, started=lambda: update_scan_job(job_id, status="running"))
        update_scan_job(job_id, status="complete", results=results)
    except Exception as exc:
        update_scan_job(job_id, status="failed", error=f"Scan failed: {exc}")


def create_scan_job(settings: ScanRequest) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    with SCAN_JOBS_LOCK:
        SCAN_JOBS[job_id] = {"job_id": job_id, "status": "queued"}
    try:
        SCAN_EXECUTOR.submit(run_scan_job, job_id, settings)
    except Exception:
        with SCAN_JOBS_LOCK:
            del SCAN_JOBS[job_id]
        raise
    with SCAN_JOBS_LOCK:
        return dict(SCAN_JOBS[job_id])


def get_scan_job(job_id: str) -> dict[str, Any] | None:
    with SCAN_JOBS_LOCK:
        job = SCAN_JOBS.get(job_id)
        return dict(job) if job is not None else None


class ImaxApiHandler(BaseHTTPRequestHandler):
    server_version = "ImaxTracker/1.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(REQUEST_TIMEOUT_SECONDS)

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, TimeoutError):
            # A disconnected Android client must not turn a completed scan into
            # a second response or prevent the next scan from starting.
            self.close_connection = True

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self.send_json(200, {"status": "ok"})
        elif path.startswith("/scan-jobs/"):
            job = get_scan_job(path.removeprefix("/scan-jobs/"))
            if job is not None:
                self.send_json(200, job)
            else:
                self.send_json(404, {"error": "Unknown scan job"})
        else:
            self.send_json(404, {"error": "Not found"})

    def read_payload(self) -> dict[str, Any]:
        if self.headers.get("Transfer-Encoding") is not None:
            raise ApiError("Transfer-Encoding is not supported; send Content-Length")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1:
            raise ApiError("Provide exactly one Content-Length header")
        value = lengths[0].strip()
        if not value or not value.isascii() or not value.isdigit():
            raise ApiError("Invalid Content-Length")
        try:
            content_length = int(value)
        except ValueError as exc:
            raise ApiError("Invalid Content-Length") from exc
        if not 0 < content_length <= MAX_REQUEST_BYTES:
            raise ApiError("Invalid request size")
        body = self.rfile.read(content_length)
        if len(body) != content_length:
            raise ApiError("Incomplete request body")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError("Malformed JSON") from exc
        if not isinstance(payload, dict):
            raise ApiError("Request must be a JSON object")
        return payload

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in {"/scan", "/scan-jobs"}:
            self.send_json(404, {"error": "Not found"})
            return
        try:
            settings = parse_scan_request(self.read_payload())
        except ApiError as exc:
            self.send_json(400, {"error": str(exc)})
            return
        except TimeoutError:
            self.send_json(408, {"error": "Timed out reading the request"})
            return

        try:
            if path == "/scan-jobs":
                status, response = 202, create_scan_job(settings)
            else:
                status, response = 200, {"results": execute_scan(settings, blocking=False)}
        except ScanBusyError as exc:
            status, response = 409, {"error": str(exc)}
        except Exception as exc:
            status, response = 500, {"error": f"Scan failed: {exc}"}
        self.send_json(status, response)

    def log_message(self, message: str, *args: object) -> None:
        print(f"{self.client_address[0]} - {message % args}", flush=True)


class ImaxApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler=ImaxApiHandler):
        self.scan_lock = SCAN_EXECUTION_LOCK
        super().__init__(address, handler)


def main() -> None:
    server = ImaxApiServer((HOST, PORT))
    print(f"IMAX Tracker API listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping IMAX Tracker API.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
