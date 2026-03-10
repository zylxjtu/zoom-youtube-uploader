from __future__ import annotations

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
                          "(stored securely in your OS credential store):\n")
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

        # The Zoom recording detail page lists individual files:
        #   "Shared screen with speaker view" (video, 44 MB)
        #   "Audio only" (13 MB)
        #   "Chat file" (257 B)
        # We need to click the VIDEO file link to navigate to its detail page,
        # then download from there, rather than using the top-level "Download"
        # button which bundles all files and may download the wrong one.

        # The Zoom recording detail page lists files with per-file action icons.
        # Next to "Shared screen with speaker view" there's a small download icon.
        # We need to find the video row and click its download icon button.

        # Strategy 1: Find the video row's per-file download icon
        # The row has: [icon] "Shared screen with speaker view" [download-icon] [link-icon] [delete-icon]
        video_labels = [
            "Shared screen with speaker view",
            "Shared screen with gallery view",
            "Speaker view",
            "Gallery view",
            "Shared screen",
            "Active speaker",
        ]

        download_triggered = False

        # Strategy 1: Find the video file's play URL (<a> with /rec/play/) and
        # convert it to a download URL (/rec/download/).
        # The page has links like: <a href="/rec/play/ABC...">Shared screen with speaker view</a>
        for label in video_labels:
            try:
                # Find <a> elements whose text matches the video label
                loc = page.locator(f'a:has-text("{label}")')
                for j in range(loc.count()):
                    el = loc.nth(j)
                    if not el.is_visible():
                        continue
                    href = el.get_attribute("href") or ""
                    if "/rec/play/" in href:
                        # Convert play URL to download URL
                        download_url = href.replace("/rec/play/", "/rec/download/")
                        console.print(f"[dim]Video download URL: {download_url}[/dim]")
                        with page.expect_download(timeout=600_000) as download_info:
                            page.evaluate(f"window.location.href = '{download_url}'")
                        download_triggered = True
                        break
                if download_triggered:
                    break
            except Exception:
                continue

        # Strategy 2: Navigate to the video play page and find a download button there
        if not download_triggered:
            for label in video_labels:
                try:
                    loc = page.locator(f'a:has-text("{label}")')
                    for j in range(loc.count()):
                        el = loc.nth(j)
                        if not el.is_visible():
                            continue
                        href = el.get_attribute("href") or ""
                        if "/rec/play/" in href or "/rec/" in href:
                            # Navigate to the individual file play page
                            play_url = href if href.startswith("http") else f"https://zoom.us{href}"
                            page.goto(play_url, wait_until="domcontentloaded")
                            page.wait_for_timeout(3000)
                            # Look for a download button on the play page
                            dl_btn = page.locator('button:has-text("Download"), a:has-text("Download")')
                            for k in range(dl_btn.count()):
                                if dl_btn.nth(k).is_visible():
                                    with page.expect_download(timeout=600_000) as download_info:
                                        dl_btn.nth(k).click()
                                    download_triggered = True
                                    break
                            break
                    if download_triggered:
                        break
                except Exception:
                    continue

        # Strategy 3: Fallback — click the top-level Download button (not Download All)
        if not download_triggered:
            try:
                # The page has "Download" and "Download All" buttons.
                # "Download" downloads just the first/selected file.
                dl_btn = page.locator('button:has-text("Download")').first
                if dl_btn.is_visible():
                    dl_btn.click()
                    page.wait_for_timeout(2000)
                    # Check for confirmation dialog
                    for sel in [
                        '[role="dialog"] button:has-text("Download")',
                        '.zm-modal-footer button:has-text("Download")',
                    ]:
                        try:
                            loc = page.locator(sel)
                            if loc.count() > 0 and loc.first.is_visible():
                                with page.expect_download(timeout=600_000) as download_info:
                                    loc.first.click()
                                download_triggered = True
                                break
                        except Exception:
                            continue
            except Exception:
                pass

        if not download_triggered:
            raise RuntimeError(
                "Could not trigger download. Try downloading manually."
            )

        download = download_info.value

        # Check for download failure
        failure = download.failure()
        if failure:
            raise RuntimeError(f"Download failed: {failure}")

        download.save_as(str(dest_path))

        # Validate the downloaded file
        size = dest_path.stat().st_size
        if size == 0:
            dest_path.unlink(missing_ok=True)
            raise RuntimeError("Downloaded file is empty (0 bytes).")

        # Check MP4 magic bytes — valid MP4s have "ftyp" at offset 4
        with open(dest_path, "rb") as f:
            header = f.read(12)
        if len(header) < 8 or header[4:8] != b"ftyp":
            snippet = header[:64]
            dest_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"Downloaded file is not a valid MP4 (header: {snippet!r}). "
                "Zoom may have returned an error page instead of the video."
            )
        # Detect audio-only M4A files (ftypM4A) — we need video (ftypmp42, ftypisom, etc.)
        ftyp_brand = header[8:12]
        if ftyp_brand == b"M4A ":
            dest_path.unlink(missing_ok=True)
            raise RuntimeError(
                "Downloaded file is audio-only (M4A), not a video MP4. "
                "The script may have downloaded 'Audio only' instead of "
                "'Shared screen with speaker view'."
            )

        console.print(f"[dim]File size: {size / (1024 * 1024):.1f} MB[/dim]")
        return dest_path

    def close_page(self) -> None:
        if self._page:
            self._page.close()
            self._page = None
