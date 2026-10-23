"""Regression checks use mocked browser interactions, never the Harkins website."""
import io
from contextlib import ExitStack, redirect_stdout
from datetime import date
import unittest
from unittest.mock import MagicMock, patch

import harkins_seat_checker as checker


class ScanResultsTests(unittest.TestCase):
    def setUp(self):
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.contexts.enter_context(redirect_stdout(io.StringIO()))
        self.contexts.enter_context(patch.object(checker, 'sync_playwright'))
        self.context = MagicMock()
        self.context.pages = [MagicMock()]
        self.contexts.enter_context(patch.object(checker, 'open_context', return_value=self.context))
        self.discover = self.contexts.enter_context(patch.object(checker, 'discover_imax_showtimes', return_value=[('9:00 AM', 'https://example.invalid/seats')]))
        self.contexts.enter_context(patch.object(checker, 'navigate'))
        self.contexts.enter_context(patch.object(checker, 'is_imax_page', return_value=True))
        self.availability = self.contexts.enter_context(patch.object(checker, 'check_page_for_availability', return_value={'F10'}))
        self.debug = self.contexts.enter_context(patch.object(checker, 'save_debug'))
        self.alert = self.contexts.enter_context(patch.object(checker, 'alert_user'))

    def scan(self):
        return checker.scan_availability(date(2026, 8, 30), date(2026, 8, 30))

    def test_debug_failure_does_not_duplicate_or_invalidate_success(self):
        self.debug.side_effect = OSError('debug directory is read-only')
        with self.assertLogs(checker.__name__, level='WARNING'):
            result = self.scan()
        self.assertEqual(result, [{'date': '2026-08-30', 'showtime': '9:00 AM', 'seats': ['F10']}])
        self.alert.assert_called_once()
        self.context.close.assert_called_once()

    def test_notification_failure_does_not_invalidate_success(self):
        self.alert.side_effect = RuntimeError('desktop notifications unavailable')
        with self.assertLogs(checker.__name__, level='WARNING'):
            result = self.scan()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['seats'], ['F10'])
        self.assertNotIn('error', result[0])

    def test_failed_seat_inspection_reports_one_error_and_continues(self):
        self.discover.return_value = [('9:00 AM', 'https://example.invalid/first'), ('12:45 PM', 'https://example.invalid/second')]
        self.availability.side_effect = [RuntimeError('seat map unavailable'), {'F10'}]
        self.debug.side_effect = OSError('disk full')
        with self.assertLogs(checker.__name__, level='WARNING'):
            result = self.scan()
        self.assertEqual(len(result), 2)
        self.assertIn('error', result[0])
        self.assertEqual(result[1]['seats'], ['F10'])
        self.assertNotIn('error', result[1])

    def test_discovery_failure_reports_one_error_when_diagnostics_also_fail(self):
        self.discover.side_effect = RuntimeError('showtimes unavailable')
        self.debug.side_effect = OSError('disk full')
        with self.assertLogs(checker.__name__, level='WARNING'):
            result = self.scan()
        self.assertEqual(len(result), 1)
        self.assertIn('Could not load showtimes', result[0]['error'])
