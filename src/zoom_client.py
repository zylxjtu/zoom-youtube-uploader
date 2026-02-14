from __future__ import annotations

import platform
import re
from datetime import date
from getpass import getpass
from pathlib import Path
from typing import List, Optional

import keyring
from playwright.sync_api import BrowserContext, Page
from rich.console import Console

from .models import ZoomRecording

console = Console()

SERVICE_NAME = "zoom-youtube-uploader"
RECORDINGS_URL = "https://zoom.us/recording"


class ZoomClient:
    def __init__(self, context: BrowserContext):
        self._context = context
        self._page: Optional[Page] = None

    def _get_page(self) -> Page:
        if self._page is None:
            self._page = self._context.new_page()
        return self._page

    def _get_credentials(self) -> tuple[str, str]:
        """Read Zoom email/password from credential manager, prompt if missing."""
        email = keyring.get_password(SERVICE_NAME, "zoom_email")
        password = keyring.get_password(SERVICE_NAME, "zoom_password")

        if not email or not password:
            console.print("Zoom credentials not found. Enter them now "
                          "(stored in Windows Credential Manager):\n")
            if not email:
                email = input("  Zoom email: ").strip()
                keyring.set_password(SERVICE_NAME, "zoom_email", email)
            if not password:
                password = getpass("  Zoom password: ")
                keyring.set_password(SERVICE_NAME, "zoom_password", password)
            print()

        return email, password

    def ensure_logged_in(self) -> None:
        """Navigate to Zoom recordings; auto-fill login if needed."""
        page = self._get_page()
        page.goto(RECORDINGS_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Zoom redirects to login if not authenticated
        if "/signin" in page.url or "/login" in page.url:
            email, password = self._get_credentials()

            console.print("Logging in to Zoom...")
            page.locator('input[type="email"], input[name="email"], #email').first.fill(email)
            page.locator('input[type="password"], input[name="password"], #password').first.fill(password)
            page.locator('button:has-text("Sign In"), button:has-text("Next"), input[type="submit"]').first.click()

            page.wait_for_timeout(3000)
            if "/signin" in page.url or "/login" in page.url:
                console.print(
                    "[yellow]Automatic login needs additional input. "
                    "Please complete login in the browser window.[/yellow]"
                )
            page.wait_for_url(
                "**/recording**", timeout=300_000
            )
            page.wait_for_load_state("domcontentloaded")

    def list_recordings(self, recording_date: date) -> List[ZoomRecording]:
        """Scrape recordings page and filter by date."""
        page = self._get_page()

        # Navigate to recordings page (no date filter in URL — it doesn't work)
        page.goto(RECORDINGS_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Build multiple date patterns to match against Zoom's display format
        # e.g. for Feb 3, 2026: match "Feb 3, 2026", "Feb 03, 2026", "2/3/2026", etc.
        target_month = recording_date.month
        target_day = recording_date.day
        target_year = recording_date.year
        date_patterns = [
            f"{recording_date.strftime('%b')} {target_day}, {target_year}",   # Feb 3, 2026
            f"{recording_date.strftime('%b')} {target_day:02d}, {target_year}", # Feb 03, 2026
            f"{target_month}/{target_day}/{target_year}",                      # 2/3/2026
            f"{target_month:02d}/{target_day:02d}/{target_year}",              # 02/03/2026
            recording_date.isoformat(),                                        # 2026-02-03
        ]

        # Regex to detect any date-like line: "Mon DD, YYYY" or "MM/DD/YYYY"
        date_line_re = re.compile(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}"
            r"|\d{1,2}/\d{1,2}/\d{4}"
        )

        # Regex to detect duration: "HH:MM:SS"
        duration_re = re.compile(r"^\d{2}:\d{2}:\d{2}$")

        # Find all recording entry links
        links = page.locator(
            'a[href*="/recording/detail"], '
            'a[href*="/rec/share"]'
        )
        count = links.count()

        if count == 0:
            return []

        recordings = []
        seen = set()

        for i in range(count):
            link = links.nth(i)
            text = link.inner_text().strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]

            # Skip short entries (duplicates with just file count + duration)
            if len(lines) <= 2:
                continue

            # Clean lines
            lines = [l for l in lines if not l.startswith("Press Shift")]

            # Find date, duration, and topic by content, not position
            date_text = ""
            duration = ""
            topic = ""

            for line in lines:
                if not date_text and date_line_re.search(line):
                    date_text = line
                elif not duration and duration_re.match(line):
                    duration = line
                elif not topic and not line.isdigit() and len(line) > 3:
                    topic = line

            if not topic:
                topic = "Unknown"

            # Filter by requested date
            if not any(pat in date_text for pat in date_patterns):
                continue

            # Deduplicate
            key = f"{topic}|{date_text}"
            if key in seen:
                continue
            seen.add(key)

            href = link.get_attribute("href") or ""

            recordings.append(ZoomRecording(
                topic=topic,
                date=date_text,
                duration=duration,
                file_size="",
                download_url=href,
            ))

        return recordings

    def download_recording(
        self,
        recording: ZoomRecording,
        dest_path: Path,
    ) -> Path:
        """Navigate to recording detail page and download the MP4."""
        page = self._get_page()

        # Navigate to the recording detail page
        url = recording.download_url
        if not url.startswith("http"):
            url = f"https://zoom.us{url}"
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Take a screenshot for debugging if needed
        # page.screenshot(path="zoom_detail_debug.png")

        # Find the download button for the recording file
        # Try multiple selectors — Zoom's UI varies
        download_btn = None
        selectors = [
            # Download buttons within the recording content area
            'button:has-text("Download")',
            'a[href*="dl=1"]',
            'a[href*="ssv="]',
            'a[href*="rec/download"]',
            '[aria-label*="ownload"]',
        ]

        for sel in selectors:
            loc = page.locator(sel)
            if loc.count() > 0:
                # Make sure it's visible (skip hidden nav links)
                for j in range(loc.count()):
                    if loc.nth(j).is_visible():
                        download_btn = loc.nth(j)
                        break
            if download_btn:
                break

        if not download_btn:
            raise RuntimeError(
                "Could not find download button on recording detail page. "
                "Try downloading manually from the browser."
            )

        # Click the download button — this may trigger a confirmation dialog
        download_btn.click()
        page.wait_for_timeout(2000)

        # Zoom may show a "Download recording files" confirmation dialog.
        # The dialog's Download button is typically inside a modal/dialog container.
        # Try several approaches to find and click the confirmation button.
        confirm_clicked = False
        for sel in [
            # Modal/dialog-specific selectors
            '.zm-modal-footer button:has-text("Download")',
            '.modal-footer button:has-text("Download")',
            '[role="dialog"] button:has-text("Download")',
            '.ReactModal__Content button:has-text("Download")',
            # The confirmation Download button is usually the LAST Download button on the page
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    with page.expect_download(timeout=600_000) as download_info:
                        loc.first.click()
                    confirm_clicked = True
                    break
            except Exception:
                continue

        if not confirm_clicked:
            # Fallback: try clicking the last visible "Download" button
            # (the confirmation dialog button appears after the original one)
            try:
                all_dl = page.locator('button:has-text("Download")')
                cnt = all_dl.count()
                if cnt > 1:
                    with page.expect_download(timeout=600_000) as download_info:
                        all_dl.nth(cnt - 1).click()
                    confirm_clicked = True
            except Exception:
                pass

        if not confirm_clicked:
            # Last resort: maybe the first click already triggered the download
            # (no confirmation dialog), re-click and wait
            with page.expect_download(timeout=600_000) as download_info:
                download_btn.click()

        download = download_info.value
        download.save_as(str(dest_path))
        return dest_path

    def close_page(self) -> None:
        if self._page:
            self._page.close()
            self._page = None
