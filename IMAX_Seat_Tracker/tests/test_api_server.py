import unittest
import time
from datetime import date
from unittest.mock import patch

import harkins_seat_checker as checker
from api_server import (
    ApiError,
    SCAN_JOBS,
    SCAN_JOBS_LOCK,
    create_scan_job,
    get_scan_job,
    parse_scan_request,
    read_scan_request,
)


class ApiRequestTests(unittest.TestCase):
    def setUp(self):
        with SCAN_JOBS_LOCK:
            SCAN_JOBS.clear()

    def test_valid_request_updates_scan_filters(self):
        start_day, end_day = read_scan_request(
            {
                "start_date": "2026-08-30",
                "end_date": "2026-09-02",
                "first_row": "F",
                "last_row": "H",
                "first_seat": 10,
                "last_seat": 25,
            }
        )

        self.assertEqual(start_day, date(2026, 8, 30))
        self.assertEqual(end_day, date(2026, 9, 2))
        self.assertEqual(checker.ALLOWED_ROWS, {"F", "G", "H"})
        self.assertEqual(checker.MIN_SEAT_NUMBER, 10)
        self.assertEqual(checker.MAX_SEAT_NUMBER, 25)

    def test_rejects_more_than_fourteen_days(self):
        with self.assertRaises(ApiError):
            read_scan_request(
                {
                    "start_date": "2026-08-30",
                    "end_date": "2026-09-13",
                    "first_row": "F",
                    "last_row": "H",
                    "first_seat": 10,
                    "last_seat": 25,
                }
            )

    def test_background_scan_job_completes_with_results(self):
        request = parse_scan_request(
            {
                "start_date": "2026-08-30",
                "end_date": "2026-08-30",
                "first_row": "F",
                "last_row": "H",
                "first_seat": 10,
                "last_seat": 25,
            }
        )
        expected = [{"date": "2026-08-30", "showtime": "11:00 AM", "seats": ["F10"]}]
        with patch.object(checker, "scan_availability", return_value=expected):
            job_id = create_scan_job(request)["job_id"]
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                job = get_scan_job(job_id)
                if job and job["status"] == "complete":
                    break
                time.sleep(0.01)

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "complete")
        self.assertEqual(job["results"], expected)


if __name__ == "__main__":
    unittest.main()
