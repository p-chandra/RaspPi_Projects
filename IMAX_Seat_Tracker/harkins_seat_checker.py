"""Scan published Harkins Odyssey IMAX 70mm sessions for open seats."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

try:
    from plyer import notification
except ImportError:
    notification = None


# A movie slug is the URL-friendly movie name between `/movies/` and the date.
# Example: https://harkins.com/movies/the-odyssey/2026-07-31 uses `the-odyssey`.
MOVIE_SLUG = "the-odyssey"
THEATRE_ID = "16"
MOVIE_ID = "HO00014201"
START_DATE = date.today()
END_DATE = START_DATE + timedelta(weeks=2)
# To set it manually, use: END_DATE = date(2026, 8, 29)
ALLOWED_ROWS: set[str] = set("FGHIJKLM")
MIN_SEAT_NUMBER: int | None = 10
MAX_SEAT_NUMBER: int | None = 25
HEADLESS = False
NAVIGATION_RETRIES = 2

try:
    import os

    if os.environ.get("DISPLAY") is None and os.environ.get("WAYLAND_DISPLAY") is None:
        HEADLESS = True
except Exception:
    HEADLESS = False

PROFILE_DIR = Path(__file__).with_name("harkins_browser_profile")
DEBUG_DIR = Path(__file__).with_name("harkins_debug")


@dataclass(frozen=True)
class Seat:
    label: str
    row: str
    number: int


def normalize_seat_label(value: str) -> str | None:
    cleaned = value.upper().strip()
    match = re.search(r"\b([A-Z]{1,2})[\s\-_:]*0*(\d{1,3})\b", cleaned)
    if not match:
        return None
    return f"{match.group(1)}{int(match.group(2))}"


def parse_seat(value: str) -> Seat | None:
    label = normalize_seat_label(value)
    if not label:
        return None
    match = re.fullmatch(r"([A-Z]{1,2})(\d+)", label)
    if not match:
        return None
    return Seat(label=label, row=match.group(1), number=int(match.group(2)))


def seat_in_requested_area(seat: Seat) -> bool:
    if ALLOWED_ROWS and seat.row not in ALLOWED_ROWS:
        return False
    if MIN_SEAT_NUMBER is not None and seat.number < MIN_SEAT_NUMBER:
        return False
    if MAX_SEAT_NUMBER is not None and seat.number > MAX_SEAT_NUMBER:
        return False
    return True


def extract_available_seat_labels(page: Page) -> set[str]:
    """Return seats that Harkins actually allows to be selected.

    Harkins places transparent buttons over every regular seat, including sold
    seats drawn as "unavailable" on the canvas.  Visibility, label, and the
    disabled attribute therefore do not indicate availability.  A real
    available seat changes ``aria-pressed`` to true when clicked; unavailable
    seats do nothing.  Probe one seat at a time and immediately deselect it.
    """
    page.locator(
        '[data-testid="auditorium-container"] button[aria-label^="Select Seat "]'
    ).first.wait_for(state="visible", timeout=30_000)

    raw_seats = page.evaluate(
        """
        async ({allowedRows, minNumber, maxNumber}) => {
          const pause = (milliseconds) =>
            new Promise((resolve) => setTimeout(resolve, milliseconds));
          const dismissSeatModal = async () => {
            const bodyText = document.body.innerText || '';
            const accessibilityDialogOpen =
              bodyText.includes('Guest with a disability or wheelchair companion') ||
              bodyText.includes('Wheelchair space');
            if (!accessibilityDialogOpen) {
              return false;
            }
            const modalButtons = Array.from(document.querySelectorAll('button'));
            const cancel = modalButtons.find((candidate) => {
              const text = (candidate.innerText || candidate.textContent || '').trim().toLowerCase();
              const visible = !!(
                candidate.offsetWidth ||
                candidate.offsetHeight ||
                candidate.getClientRects().length
              );
              return visible && text === 'cancel';
            });
            if (cancel) {
              cancel.click();
              await pause(50);
              return true;
            }
            return false;
          };
          const buttons = Array.from(
            document.querySelectorAll(
              '[data-testid="auditorium-container"] button[aria-label^="Select Seat "]'
            )
          );
          const parsedButtons = buttons.map((button) => {
            const match = (button.id || '').toUpperCase().match(/^([A-Z]{1,2})(\\d+)$/);
            return match
              ? {button, row: match[1], number: Number(match[2])}
              : null;
          }).filter(Boolean);
          const available = [];

          for (const item of parsedButtons) {
            const {button, row, number} = item;
            if (
              !allowedRows.includes(row) ||
              (minNumber !== null && number < minNumber) ||
              (maxNumber !== null && number > maxNumber)
            ) {
              continue;
            }
            if (!(button.offsetWidth || button.offsetHeight || button.getClientRects().length)) {
              continue;
            }

            // Clear a selection left behind by an interrupted previous check.
            if (button.getAttribute('aria-pressed') === 'true') {
              button.click();
              await pause(25);
            }

            button.click();
            await pause(25);
            // Wheelchair/accessibility spaces open a confirmation instead of
            // selecting a normal seat. They must not be reported as available.
            if (await dismissSeatModal()) {
              continue;
            }
            if (button.getAttribute('aria-pressed') === 'true') {
              available.push(button.id);
              button.click();
              await pause(25);
            }
          }
          return available;
        }
        """,
        {
            "allowedRows": sorted(ALLOWED_ROWS),
            "minNumber": MIN_SEAT_NUMBER,
            "maxNumber": MAX_SEAT_NUMBER,
        },
    )

    available: set[str] = set()
    for raw_label in raw_seats:
        label = normalize_seat_label(str(raw_label))
        if label:
            available.add(label)
    return available


def build_movie_url(day: date) -> str:
    return f"https://harkins.com/movies/{MOVIE_SLUG}/{day:%Y-%m-%d}"


def build_ticketing_url(href: str) -> str:
    """Return an absolute Harkins URL for a discovered ticketing link."""
    return urljoin("https://harkins.com/", href)


def navigate(page: Page, url: str, ready_selector: str) -> None:
    """Navigate with one retry and wait for the content actually needed."""
    last_error: Exception | None = None
    for _attempt in range(1, NAVIGATION_RETRIES + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.locator(ready_selector).first.wait_for(state="visible", timeout=30_000)
            return
        except PlaywrightTimeoutError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def select_metro_phoenix(page: Page) -> None:
    """Select the Metro Phoenix market when Harkins has not restored it."""
    filter_button = page.locator("#filter-btn-handler")
    filter_button.wait_for(state="attached", timeout=15_000)
    filter_button.evaluate("(button) => button.click()")

    metro_button = page.locator("button", has_text="Metro Phoenix AZ").last
    metro_button.wait_for(state="attached", timeout=15_000)
    metro_button.evaluate("(button) => button.click()")

    apply_button = page.locator("#filter-apply-handler")
    if apply_button.count():
        apply_button.evaluate("(button) => button.click()")


def discover_imax_showtimes(page: Page, day: date) -> list[tuple[str, str]]:
    """Find the real Arizona Mills IMAX 70mm session links for ``day``.

    Session IDs, unlike the date suffix on a ticketing URL, identify one
    specific performance.  The movie page supplies the correct session IDs for
    each date.  On the Arizona Mills card the premium IMAX 70mm group is the
    first ordered showtime list and the separately labelled Digital group is
    the next one.
    """
    navigate(page, build_movie_url(day), "body")

    theatre_link = page.locator(
        f'a[href$="/theatres/arizona-mills-w-imax/{day:%Y-%m-%d}"]',
        has_text="Arizona Mills w/ IMAX",
    ).first
    try:
        theatre_link.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError:
        select_metro_phoenix(page)
        try:
            theatre_link.wait_for(state="visible", timeout=30_000)
        except PlaywrightTimeoutError:
            return []
    theatre_card = theatre_link.locator("xpath=ancestor::div[contains(@class, 'container')][1]")
    premium_showtimes = theatre_card.locator(
        f'a[href*="/ticketing/theatre/{THEATRE_ID}/movie/{MOVIE_ID}/session/"]'
    )

    discovered: list[tuple[str, str]] = []
    for link in premium_showtimes.all():
        showtime = link.inner_text(timeout=5_000).strip()
        href = link.get_attribute("href")
        if showtime and href:
            discovered.append((showtime, build_ticketing_url(href)))
    return discovered


def is_imax_page(page: Page) -> bool:
    body_text = page.locator("body").inner_text(timeout=15_000)
    return "IMAX" in body_text.upper()


def save_debug(page: Page, available: Iterable[str], prefix: str = "latest") -> None:
    DEBUG_DIR.mkdir(exist_ok=True)
    page.screenshot(path=str(DEBUG_DIR / f"{prefix}_page.png"), full_page=True)
    (DEBUG_DIR / "available_seats.json").write_text(json.dumps(sorted(available), indent=2), encoding="utf-8")
    (DEBUG_DIR / f"{prefix}_page.html").write_text(page.content(), encoding="utf-8")


def alert_user(day: date, showtime: str, seats: list[str]) -> None:
    message = f"{day:%Y-%m-%d} {showtime}: {', '.join(seats)}"
    print("\a" * 3, end="")
    if notification is not None:
        try:
            notification.notify(title="Harkins seats available", message=message, timeout=30)
        except Exception:
            pass


def close_context_safely(context: BrowserContext | object) -> None:
    try:
        context.close()
    except Exception as exc:
        if "Target page, context or browser has been closed" in str(exc):
            return
        raise


def open_context(playwright) -> BrowserContext:
    PROFILE_DIR.mkdir(exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=HEADLESS,
        viewport={"width": 1400, "height": 1000},
        args=["--disable-blink-features=AutomationControlled"],
    )


def format_showtime_summary(day: date, showtime: str, seats: Iterable[str]) -> str:
    requested_seats: list[Seat] = []
    for label in seats:
        seat = parse_seat(label)
        if seat and seat_in_requested_area(seat):
            requested_seats.append(seat)
    seat_list = ", ".join(
        seat.label for seat in sorted(requested_seats, key=lambda seat: (seat.row, seat.number))
    )
    return f"{day:%Y-%m-%d} | {showtime} | {seat_list or 'None'}"


def check_page_for_availability(page: Page) -> set[str]:
    return extract_available_seat_labels(page)


def scan_availability(start_day: date, end_day: date) -> list[dict[str, object]]:
    """Scan a date range and return results suitable for an API response."""
    results: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        context = open_context(playwright)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            current_day = start_day
            while current_day <= end_day:
                try:
                    showtimes = discover_imax_showtimes(page, current_day)
                except Exception as exc:
                    try:
                        save_debug(page, [], prefix="discovery_error")
                    except Exception:
                        pass
                    results.append(
                        {
                            "date": current_day.isoformat(),
                            "showtime": "",
                            "seats": [],
                            "error": f"Could not load showtimes: {exc}",
                        }
                    )
                    current_day += timedelta(days=1)
                    continue

                if not showtimes:
                    current_day += timedelta(days=1)
                    continue

                for showtime, ticketing_url in showtimes:
                    try:
                        navigate(page, ticketing_url, '[data-testid="auditorium-seatmap"]')

                        if not is_imax_page(page):
                            continue

                        available = check_page_for_availability(page)
                        print(format_showtime_summary(current_day, showtime, available))

                        seats = [
                            seat.label
                            for seat in sorted(
                                (parse_seat(label) for label in available),
                                key=lambda seat: (seat.row, seat.number),
                            )
                            if seat is not None
                        ]
                        results.append(
                            {
                                "date": current_day.isoformat(),
                                "showtime": showtime,
                                "seats": seats,
                            }
                        )

                        if available:
                            save_debug(page, available, prefix="match")
                            alert_user(current_day, showtime, seats)
                    except Exception as exc:
                        try:
                            save_debug(page, [], prefix="showtime_error")
                        except Exception:
                            pass
                        results.append(
                            {
                                "date": current_day.isoformat(),
                                "showtime": showtime,
                                "seats": [],
                                "error": f"Could not inspect seats: {exc}",
                            }
                        )

                current_day += timedelta(days=1)
        finally:
            close_context_safely(context)
    return results


def main() -> None:
    scan_availability(START_DATE, END_DATE)


if __name__ == "__main__":
    main()
