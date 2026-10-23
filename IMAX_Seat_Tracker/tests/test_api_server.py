import http.client
import json
import socket
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest.mock import patch

import api_server
import harkins_seat_checker as checker
from api_server import ApiError, ImaxApiHandler, ImaxApiServer, parse_scan_request


def scan_payload(**overrides):
    payload = {"start_date": "2026-08-30", "end_date": "2026-09-02",
               "first_row": "F", "last_row": "H", "first_seat": 10, "last_seat": 25}
    return dict(payload, **overrides)


def filters():
    return (checker.ALLOWED_ROWS.copy(), checker.MIN_SEAT_NUMBER, checker.MAX_SEAT_NUMBER, checker.HEADLESS)


class ApiRequestTests(unittest.TestCase):
    def test_valid_request_does_not_mutate_active_scan_filters(self):
        original = filters()
        request = parse_scan_request(scan_payload())
        self.assertEqual(request.start_day, date(2026, 8, 30))
        self.assertEqual(request.end_day, date(2026, 9, 2))
        self.assertEqual((request.first_row, request.last_row, request.first_seat, request.last_seat), ('F', 'H', 10, 25))
        self.assertEqual(filters(), original)

    def test_invalid_ranges(self):
        for overrides in ({'end_date': '2026-09-13'}, {'end_date': '2026-08-29'},
                          {'first_row': 'Z', 'last_row': 'A'}, {'first_seat': 30, 'last_seat': 10}):
            with self.subTest(overrides=overrides), self.assertRaises(ApiError):
                parse_scan_request(scan_payload(**overrides))


class QuietHandler(ImaxApiHandler):
    def log_message(self, *args):
        pass


class HttpFixture(unittest.TestCase):
    def setUp(self):
        self.server = ImaxApiServer(('127.0.0.1', 0), QuietHandler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, payload=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        try:
            body = json.dumps(payload) if payload is not None else None
            connection.request(method, path, body=body, headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def raw_request(self, headers, body=b'{}', half_close=False):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        try:
            connection.putrequest('POST', '/scan')
            for key, value in headers:
                connection.putheader(key, value)
            connection.endheaders(body)
            if half_close:
                connection.sock.shutdown(socket.SHUT_WR)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()


class HttpApiTests(HttpFixture):
    def test_android_request_and_response_unchanged(self):
        original = filters()
        results = [{'date': '2026-08-30', 'showtime': '9:00 AM', 'seats': ['F10']}]

        def inspect(start, end):
            self.assertEqual((start, end), (date(2026, 8, 30), date(2026, 9, 2)))
            self.assertEqual(filters(), (set('FGH'), 10, 25, True))
            return results

        with patch.object(checker, 'scan_availability', side_effect=inspect):
            self.assertEqual(self.request('POST', '/scan', scan_payload()), (200, {'results': results}))
        self.assertEqual(filters(), original)

    def test_health_and_busy_response_while_scanning_preserve_active_settings(self):
        entered, release = threading.Event(), threading.Event()
        original = filters()

        def blocked_scan(*args):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError('Test failed to release blocked scan')
            self.assertEqual(filters(), (set('FGH'), 10, 25, True))
            return []

        with patch.object(checker, 'scan_availability', side_effect=blocked_scan) as scan:
            with ThreadPoolExecutor(max_workers=1) as pool:
                running = pool.submit(self.request, 'POST', '/scan', scan_payload())
                try:
                    self.assertTrue(entered.wait(timeout=2))
                    self.assertEqual(self.request('GET', '/health'), (200, {'status': 'ok'}))
                    self.assertFalse(running.done())
                    status, body = self.request('POST', '/scan', scan_payload(first_row='A', last_row='B', first_seat=1, last_seat=2))
                    self.assertEqual(status, 409)
                    self.assertIn('already running', body['error'])
                    self.assertEqual(filters(), (set('FGH'), 10, 25, True))
                    self.assertEqual(scan.call_count, 1)
                finally:
                    release.set()
                self.assertEqual(running.result(timeout=2), (200, {'results': []}))
        self.assertEqual(filters(), original)

    def test_failed_scan_releases_lock_and_restores_settings(self):
        original = filters()
        with patch.object(checker, 'scan_availability', side_effect=[RuntimeError('browser unavailable'), []]):
            self.assertEqual(self.request('POST', '/scan', scan_payload())[0], 500)
            self.assertEqual(filters(), original)
            self.assertEqual(self.request('POST', '/scan', scan_payload()), (200, {'results': []}))
        self.assertEqual(filters(), original)

    def test_bad_headers_and_bodies_return_400_without_scanning(self):
        cases = [
            ([('Content-Length', 'bad')], b'{}', False),
            ([('Content-Length', '-1')], b'{}', False),
            ([('Content-Length', '0')], b'', False),
            ([('Content-Length', '16385')], b'', False),
            ([], b'{}', False),
            ([('Content-Length', '2'), ('Content-Length', '2')], b'{}', False),
            ([('Content-Length', '2'), ('Transfer-Encoding', 'chunked')], b'{}', False),
            ([('Content-Length', '2')], b'{?', False),
            ([('Content-Length', '1')], b'\xff', False),
            ([('Content-Length', '2')], b'[]', False),
            ([('Content-Length', '9')], b'{}', True),
        ]
        with patch.object(checker, 'scan_availability') as scan:
            for headers, body, half_close in cases:
                with self.subTest(headers=headers, body=body):
                    status, response = self.raw_request(headers, body, half_close)
                    self.assertEqual(status, 400)
                    self.assertIn('error', response)
            scan.assert_not_called()

    def test_partial_request_times_out_without_blocking_health(self):
        with patch.object(api_server, 'REQUEST_TIMEOUT_SECONDS', 0.2):
            connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
            try:
                connection.putrequest('POST', '/scan')
                connection.putheader('Content-Length', '20')
                connection.endheaders(b'{}')
                self.assertEqual(self.request('GET', '/health'), (200, {'status': 'ok'}))
                response = connection.getresponse()
                self.assertEqual(response.status, 408)
                response.read()
            finally:
                connection.close()

    def test_disconnected_client_does_not_leave_scan_locked(self):
        entered, release = threading.Event(), threading.Event()

        def blocked_scan(*args):
            entered.set()
            release.wait(timeout=2)
            return []

        with patch.object(checker, 'scan_availability', side_effect=blocked_scan):
            connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
            connection.request('POST', '/scan', body=json.dumps(scan_payload()))
            try:
                self.assertTrue(entered.wait(timeout=2))
                connection.close()
            finally:
                connection.close()
                release.set()
            self.assertTrue(self.server.scan_lock.acquire(timeout=2))
            self.server.scan_lock.release()
        with patch.object(checker, 'scan_availability', return_value=[]):
            self.assertEqual(self.request('POST', '/scan', scan_payload())[0], 200)


if __name__ == '__main__':
    unittest.main()
