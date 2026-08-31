"""Private HTTP API for the IMAX Tracker Android application."""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import harkins_seat_checker as checker


HOST = "0.0.0.0"
PORT = 8000
MAX_SCAN_DAYS = 14
SCAN_JOBS: dict[str, dict[str, Any]] = {}
SCAN_JOBS_LOCK = threading.Lock()
SCAN_EXECUTION_LOCK = threading.Lock()
SCAN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="imax-scan")


class ApiError(ValueError):
    pass


@dataclass(frozen=True)
class ScanRequest:
    start_day: date
    end_day: date
    allowed_rows: frozenset[str]
    first_seat: int
    last_seat: int


def parse_scan_request(payload: dict[str, Any]) -> ScanRequest:
    try:
        start_day = date.fromisoformat(str(payload["start_date"]))
        end_day = date.fromisoformat(str(payload["end_date"]))
        first_row = str(payload["first_row"]).upper()
        last_row = str(payload["last_row"]).upper()
        first_seat = int(payload["first_seat"])
        last_seat = int(payload["last_seat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError("Invalid or missing scan settings") from exc

    if end_day < start_day:
        raise ApiError("End date must not be before start date")
    if (end_day - start_day).days + 1 > MAX_SCAN_DAYS:
        raise ApiError(f"Date range cannot exceed {MAX_SCAN_DAYS} days")
    if not (len(first_row) == len(last_row) == 1 and "A" <= first_row <= last_row <= "Z"):
        raise ApiError("Invalid row range")
    if not (1 <= first_seat <= last_seat <= 100):
        raise ApiError("Invalid seat-number range")

    allowed_rows = frozenset(
        chr(row) for row in range(ord(first_row), ord(last_row) + 1)
    )
    return ScanRequest(start_day, end_day, allowed_rows, first_seat, last_seat)


def apply_scan_request(request: ScanRequest) -> None:
    checker.ALLOWED_ROWS = set(request.allowed_rows)
    checker.MIN_SEAT_NUMBER = request.first_seat
    checker.MAX_SEAT_NUMBER = request.last_seat
    checker.HEADLESS = True


def read_scan_request(payload: dict[str, Any]) -> tuple[date, date]:
    """Validate a legacy synchronous request and update scanner filters."""
    request = parse_scan_request(payload)
    apply_scan_request(request)
    return request.start_day, request.end_day


def execute_scan(request: ScanRequest) -> list[dict[str, object]]:
    """Run one scan at a time because the scanner uses process-wide filters."""
    with SCAN_EXECUTION_LOCK:
        apply_scan_request(request)
        return checker.scan_availability(request.start_day, request.end_day)


def update_scan_job(job_id: str, **updates: Any) -> None:
    with SCAN_JOBS_LOCK:
        job = SCAN_JOBS.get(job_id)
        if job is not None:
            job.update(updates)


def run_scan_job(job_id: str, request: ScanRequest) -> None:
    update_scan_job(job_id, status="running")
    try:
        results = execute_scan(request)
        update_scan_job(job_id, status="complete", results=results)
    except Exception as exc:
        update_scan_job(job_id, status="failed", error=f"Scan failed: {exc}")


def create_scan_job(request: ScanRequest) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    job: dict[str, Any] = {"job_id": job_id, "status": "queued"}
    with SCAN_JOBS_LOCK:
        SCAN_JOBS[job_id] = job
    SCAN_EXECUTOR.submit(run_scan_job, job_id, request)
    return dict(job)


def get_scan_job(job_id: str) -> dict[str, Any] | None:
    with SCAN_JOBS_LOCK:
        job = SCAN_JOBS.get(job_id)
        return dict(job) if job is not None else None


class ImaxApiHandler(BaseHTTPRequestHandler):
    server_version = "ImaxTracker/1.0"

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self.send_json(200, {"status": "ok"})
        elif path.startswith("/scan-jobs/"):
            job_id = path.removeprefix("/scan-jobs/")
            job = get_scan_job(job_id)
            if job is None:
                self.send_json(404, {"error": "Unknown scan job"})
            else:
                self.send_json(200, job)
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in {"/scan", "/scan-jobs"}:
            self.send_json(404, {"error": "Not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 16_384:
                raise ApiError("Invalid request size")
            payload = json.loads(self.rfile.read(content_length))
            if not isinstance(payload, dict):
                raise ApiError("Request must be a JSON object")
            request = parse_scan_request(payload)
            if path == "/scan-jobs":
                self.send_json(202, create_scan_job(request))
            else:
                self.send_json(200, {"results": execute_scan(request)})
        except ApiError as exc:
            self.send_json(400, {"error": str(exc)})
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Malformed JSON"})
        except Exception as exc:
            self.send_json(500, {"error": f"Scan failed: {exc}"})

    def log_message(self, message: str, *args: object) -> None:
        print(f"{self.client_address[0]} - {message % args}")


def main() -> None:
    server = HTTPServer((HOST, PORT), ImaxApiHandler)
    print(f"IMAX Tracker API listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping IMAX Tracker API.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
