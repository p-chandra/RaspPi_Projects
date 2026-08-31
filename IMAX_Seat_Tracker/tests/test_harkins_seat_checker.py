import unittest
from datetime import date

from harkins_seat_checker import (
    Seat,
    build_movie_url,
    build_ticketing_url,
    close_context_safely,
    format_showtime_summary,
    normalize_seat_label,
    parse_seat,
)


class SeatMatchingTests(unittest.TestCase):
    def test_movie_url_changes_with_date(self):
        self.assertEqual(
            build_movie_url(date(2026, 8, 2)),
            "https://harkins.com/movies/the-odyssey/2026-08-02",
        )

    def test_ticketing_url_makes_relative_href_absolute(self):
        self.assertEqual(
            build_ticketing_url("/ticketing/theatre/16/movie/HO00014201/session/570549"),
            "https://harkins.com/ticketing/theatre/16/movie/HO00014201/session/570549",
        )

    def test_ticketing_url_preserves_absolute_href(self):
        self.assertEqual(
            build_ticketing_url("https://harkins.com/ticketing/session/570549"),
            "https://harkins.com/ticketing/session/570549",
        )

    def test_normalize_seat_label_handles_common_formats(self):
        self.assertEqual(normalize_seat_label("Seat F-12"), "F12")
        self.assertEqual(normalize_seat_label("C 3"), "C3")

    def test_parse_seat_returns_expected_row_and_number(self):
        self.assertEqual(parse_seat("A12"), Seat("A12", "A", 12))

    def test_format_showtime_summary_lists_seats(self):
        self.assertEqual(
            format_showtime_summary(
                date(2026, 8, 1),
                "9:00 AM",
                ["F9", "F10", "F11", "M26"],
            ),
            "2026-08-01 | 9:00 AM | F10, F11",
        )

    def test_close_context_safely_ignores_already_closed_context(self):
        class DummyContext:
            def close(self):
                raise RuntimeError("Target page, context or browser has been closed")

        close_context_safely(DummyContext())


if __name__ == "__main__":
    unittest.main()
