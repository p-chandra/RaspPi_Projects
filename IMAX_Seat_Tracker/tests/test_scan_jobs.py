"""Exercise the job API and its shared execution gate with legacy clients."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import threading
import time
from unittest.mock import patch

import api_server
import harkins_seat_checker as checker
from test_api_server import HttpFixture, filters, scan_payload


class ScanJobTests(HttpFixture):
    def setUp(self):
        super().setUp()
        with api_server.SCAN_JOBS_LOCK:
            api_server.SCAN_JOBS.clear()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.contexts.enter_context(patch.object(api_server, 'SCAN_EXECUTOR', self.executor))
        self.scan = self.contexts.enter_context(patch.object(checker, 'scan_availability', return_value=[]))
        # Join workers before restoring mocks, including when an assertion fails.
        self.addCleanup(lambda: self.executor.shutdown(wait=True, cancel_futures=True))

    def wait_for_job(self, job_id):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status, job = self.request('GET', '/scan-jobs/' + job_id + '?poll=1')
            self.assertEqual(status, 200)
            if job['status'] in {'complete', 'failed'}:
                return job
            time.sleep(0.01)
        self.fail('Background scan did not finish')

    def test_jobs_queue_with_isolated_settings_and_survive_client_disconnect(self):
        entered, release = threading.Event(), threading.Event()
        original = filters()
        observed = []

        def scan(*args):
            observed.append(filters())
            if len(observed) == 1:
                entered.set()
                release.wait(timeout=5)
                self.assertEqual(filters(), observed[0])
            return [{'date': '2026-08-30', 'showtime': '9:00 AM', 'seats': ['F10']}]

        self.scan.side_effect = scan
        try:
            status, first = self.request('POST', '/scan-jobs', scan_payload())
            self.assertEqual(status, 202)
            self.assertTrue(entered.wait(timeout=2))
            self.assertEqual(self.request('GET', '/health'), (200, {'status': 'ok'}))
            status, second = self.request('POST', '/scan-jobs', scan_payload(first_row='A', last_row='B', first_seat=1, last_seat=2))
            self.assertEqual(status, 202)
            self.assertEqual(self.request('GET', '/scan-jobs/' + second['job_id'])[1]['status'], 'queued')
            self.assertEqual(self.request('POST', '/scan', scan_payload())[0], 409)
            self.assertEqual(filters(), (set('FGH'), 10, 25, True))
        finally:
            release.set()
        for job in (first, second):
            complete = self.wait_for_job(job['job_id'])
            self.assertEqual(complete['status'], 'complete')
            self.assertEqual(complete['results'][0]['seats'], ['F10'])
        self.assertEqual(observed, [(set('FGH'), 10, 25, True), (set('AB'), 1, 2, True)])
        self.assertEqual(filters(), original)

    def test_background_job_waits_for_legacy_scan_without_changing_filters(self):
        entered, release = threading.Event(), threading.Event()
        observed = []

        def scan(*args):
            observed.append(filters())
            if len(observed) == 1:
                entered.set()
                release.wait(timeout=5)
                self.assertEqual(filters(), (set('FGH'), 10, 25, True))
            return []

        self.scan.side_effect = scan
        with ThreadPoolExecutor(max_workers=1) as client:
            legacy = client.submit(self.request, 'POST', '/scan', scan_payload())
            try:
                self.assertTrue(entered.wait(timeout=2))
                status, job = self.request('POST', '/scan-jobs', scan_payload(first_row='A', last_row='B'))
                self.assertEqual(status, 202)
                self.assertEqual(self.request('GET', '/scan-jobs/' + job['job_id'])[1]['status'], 'queued')
                self.assertEqual(len(observed), 1)
                self.assertEqual(self.request('GET', '/health')[0], 200)
            finally:
                release.set()
            self.assertEqual(legacy.result(timeout=2)[0], 200)
        self.assertEqual(self.wait_for_job(job['job_id'])['status'], 'complete')
        self.assertEqual(observed[1], (set('AB'), 10, 25, True))

    def test_failed_job_does_not_block_later_jobs_or_leave_filters_changed(self):
        original = filters()
        self.scan.side_effect = [RuntimeError('browser unavailable'), []]
        status, first = self.request('POST', '/scan-jobs', scan_payload())
        self.assertEqual(status, 202)
        result = self.wait_for_job(first['job_id'])
        self.assertEqual(result['status'], 'failed')
        self.assertIn('browser unavailable', result['error'])
        self.assertEqual(filters(), original)
        status, second = self.request('POST', '/scan-jobs', scan_payload())
        self.assertEqual(status, 202)
        self.assertEqual(self.wait_for_job(second['job_id'])['status'], 'complete')
        self.assertEqual(filters(), original)

    def test_unknown_jobs_and_invalid_job_requests(self):
        self.assertEqual(self.request('GET', '/scan-jobs/unknown')[0], 404)
        self.assertEqual(self.request('POST', '/scan-jobs', {})[0], 400)
        with api_server.SCAN_JOBS_LOCK:
            self.assertFalse(api_server.SCAN_JOBS)
        self.scan.assert_not_called()
