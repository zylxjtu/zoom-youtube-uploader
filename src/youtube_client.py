from __future__ import annotations

import platform
from pathlib import Path
from typing import Optional

from playwright.sync_api import BrowserContext, Page
from rich.console import Console

from .models import UploadResult

console = Console()


class YouTubeClient:
    def __init__(self, context: BrowserContext):
        self._context = context
        self._page: Optional[Page] = None

    def _get_page(self) -> Page:
        if self._page is None:
            self._page = self._context.new_page()
        return self._page

    def _dismiss_overlays(self) -> None:
        """Press Escape to close any open dialogs/overlays."""
        try:
            self._page.keyboard.press("Escape")
            self._page.wait_for_timeout(500)
        except Exception:
            pass

    def ensure_logged_in(self) -> None:
        """Navigate to YouTube Studio; if not logged in, wait for user."""
        page = self._get_page()
        page.goto("https://studio.youtube.com")
        page.wait_for_load_state("domcontentloaded")

        if "accounts.google.com" in page.url:
            console.print(
                "[yellow]Please log in to your Google account "
                "in the browser window.[/yellow]"
            )
            page.wait_for_url(
                "**/studio.youtube.com/**", timeout=300_000
            )
            page.wait_for_load_state("domcontentloaded")

    def upload_video(
        self,
        file_path: Path,
        title: str,
        description: str,
        privacy_status: str = "public",
        made_for_kids: bool = False,
        thumbnail_file: Optional[str] = None,
        playlist_name: Optional[str] = None,
    ) -> UploadResult:
        """Upload a video through YouTube Studio UI."""
        page = self._get_page()
        file_path = Path(file_path).resolve()

        # Navigate to YouTube Studio
        page.goto("https://studio.youtube.com")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        # Try multiple selectors for the CREATE button
        create_btn = None
        for sel in [
            "#create-icon",
            '[aria-label="Create"]',
            'button:has-text("Create")',
            "#upload-icon",
        ]:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                create_btn = loc.first
                break

        if create_btn:
            create_btn.click()
            page.get_by_text("Upload videos").click()
        else:
            page.goto("https://studio.youtube.com/channel/UC/videos/upload?d=ud")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)

        # Set file via hidden input
        page.locator('input[type="file"]').set_input_files(str(file_path))

        # Wait for details form
        page.wait_for_selector("#title-textarea", timeout=60_000)
        page.wait_for_timeout(1500)

        # --- Details step ---

        # Set title
        title_box = page.locator("#title-textarea #textbox")
        title_box.click()
        select_all = "Meta+a" if platform.system() == "Darwin" else "Control+a"
        page.keyboard.press(select_all)
        page.keyboard.type(title, delay=15)

        # Set description
        desc_box = page.locator("#description-textarea #textbox")
        desc_box.click()
        page.keyboard.type(description, delay=15)

        # Set thumbnail
        if thumbnail_file:
            self._set_thumbnail(thumbnail_file)

        # Set playlist
        if playlist_name:
            self._set_playlist(playlist_name)

        # Scroll down to "made for kids" section
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(500)

        # Set audience (made for kids)
        kids_name = "NOT_MADE_FOR_KIDS" if not made_for_kids else "MADE_FOR_KIDS"
        try:
            page.locator(f'[name="{kids_name}"]').click(timeout=5000)
        except Exception:
            try:
                label = "No, it's not made for kids" if not made_for_kids else "Yes, it's made for kids"
                page.get_by_text(label, exact=False).first.click(timeout=5000)
            except Exception:
                console.print("[yellow]Could not set 'made for kids' — skipping.[/yellow]")

        page.wait_for_timeout(1000)

        # --- Click NEXT through: Video elements → Checks → Visibility ---
        for step in range(3):
            try:
                page.locator("#next-button").click(timeout=10_000)
                page.wait_for_timeout(2000)
            except Exception:
                console.print(f"[yellow]Could not click Next at step {step + 1}.[/yellow]")
                page.screenshot(path=f"yt_debug_step{step + 1}.png")

        # --- Visibility step ---
        try:
            page.locator(f'[name="{privacy_status.upper()}"]').click(timeout=5000)
        except Exception:
            try:
                page.get_by_role("radio", name=privacy_status.capitalize()).click(timeout=5000)
            except Exception:
                console.print(f"[yellow]Could not set visibility to '{privacy_status}'.[/yellow]")
                page.screenshot(path="yt_debug_visibility.png")

        page.wait_for_timeout(1000)

        # Wait for upload/processing to finish while checking for errors
        try:
            page.wait_for_function(
                """() => {
                    // Check for error states in the upload dialog
                    const errorSelectors = [
                        '.error-area',
                        '.error-message',
                        '[class*="error"]',
                        '.upload-error',
                    ];
                    for (const sel of errorSelectors) {
                        const el = document.querySelector(sel);
                        if (el && el.offsetParent !== null && el.textContent.trim()) {
                            const text = el.textContent.trim().toLowerCase();
                            if (text.includes('abandoned') || text.includes('failed')
                                || text.includes('error') || text.includes('problem')
                                || text.includes('can\\'t process') || text.includes('unable')) {
                                window.__ytUploadError = el.textContent.trim();
                                return true;
                            }
                        }
                    }

                    // Check all visible text for "processing abandoned"
                    const body = document.body.innerText.toLowerCase();
                    if (body.includes('processing abandoned')
                        || body.includes('upload failed')
                        || body.includes('can\\'t process this video')
                        || body.includes('server rejected')) {
                        window.__ytUploadError = 'Upload error detected in page';
                        return true;
                    }

                    // Check if done button is enabled (upload succeeded)
                    const btn = document.querySelector('#done-button');
                    if (btn && btn.getAttribute('aria-disabled') !== 'true') {
                        window.__ytUploadError = '';
                        return true;
                    }
                    return false;
                }""",
                timeout=600_000,
            )
        except Exception as e:
            page.screenshot(path="yt_debug_upload_timeout.png")
            progress = self._get_upload_status_text()
            raise RuntimeError(
                f"Upload timed out. Progress at timeout: {progress}. "
                f"Screenshot saved to yt_debug_upload_timeout.png"
            ) from e

        # Check if the wait ended due to an error rather than success
        upload_error = page.evaluate("() => window.__ytUploadError || ''")
        if upload_error:
            page.screenshot(path="yt_debug_upload_error.png")
            status_text = self._get_upload_status_text()
            raise RuntimeError(
                f"YouTube upload error: {upload_error}. "
                f"Status text: {status_text}. "
                f"Screenshot saved to yt_debug_upload_error.png"
            )

        page.wait_for_timeout(1000)

        # Click Publish/Save — use #done-button directly, not text matching
        try:
            page.locator("#done-button").click(timeout=10_000)
        except Exception:
            # Try role-based button match
            try:
                page.get_by_role("button", name="Publish").click(timeout=5000)
            except Exception:
                try:
                    page.get_by_role("button", name="Save").click(timeout=5000)
                except Exception:
                    page.screenshot(path="yt_debug_publish.png")
                    raise RuntimeError("Could not click Publish/Save button.")

        # Wait for success dialog and extract video URL
        page.wait_for_timeout(5000)
        video_id = self._extract_video_id()

        return UploadResult(video_id=video_id, title=title)

    def _set_thumbnail(self, thumbnail_path: str) -> None:
        """Upload a thumbnail from a local file."""
        page = self._page
        resolved = str(Path(thumbnail_path).resolve())

        # Try clicking "Upload thumbnail" and handling file chooser
        try:
            with page.expect_file_chooser(timeout=5000) as fc_info:
                page.get_by_text("Upload thumbnail", exact=False).first.click()
            fc_info.value.set_files(resolved)
            page.wait_for_timeout(2000)
            return
        except Exception:
            pass

        # Try file inputs that accept images
        for sel in [
            'input[type="file"][accept*="image"]',
            '#still-picker input[type="file"]',
        ]:
            try:
                page.locator(sel).first.set_input_files(resolved, timeout=3000)
                page.wait_for_timeout(2000)
                return
            except Exception:
                continue

        console.print("[yellow]Could not set thumbnail — skipping.[/yellow]")
        page.screenshot(path="yt_debug_thumbnail.png")

    def _set_playlist(self, playlist_name: str) -> None:
        """Select a playlist by name in the details step."""
        page = self._page
        try:
            # Open playlist selector
            page.locator("ytcp-video-metadata-playlists").click(timeout=5000)
            page.wait_for_timeout(1000)

            # Check the target playlist
            checkbox = page.locator(f'label:has-text("{playlist_name}")')
            if checkbox.count() > 0:
                checkbox.first.click()
                page.wait_for_timeout(500)
            else:
                console.print(f"[yellow]Playlist '{playlist_name}' not found — skipping.[/yellow]")

            # Always close the dialog (click Done inside the playlist dialog)
            try:
                page.locator("ytcp-playlist-dialog").get_by_text("Done", exact=True).click(timeout=3000)
            except Exception:
                # Press Escape to dismiss if Done button not found
                self._dismiss_overlays()

            page.wait_for_timeout(500)
        except Exception as e:
            console.print(f"[yellow]Could not set playlist — skipping.[/yellow]")
            self._dismiss_overlays()

    def _get_upload_status_text(self) -> str:
        """Extract upload progress/status text from the YouTube Studio dialog."""
        page = self._page
        try:
            return page.evaluate("""() => {
                const parts = [];

                // Look for progress text (e.g., "Uploading 45%..." or "Processing...")
                const progressSelectors = [
                    '.progress-label',
                    '.upload-progress',
                    '.status-text',
                    'ytcp-upload-progress-bar',
                    '.upload-status',
                    '[class*="progress"]',
                    '[class*="upload"] [class*="status"]',
                ];
                for (const sel of progressSelectors) {
                    const el = document.querySelector(sel);
                    if (el && el.textContent.trim()) {
                        parts.push(sel + ': ' + el.textContent.trim().substring(0, 200));
                    }
                }

                // Grab text from the upload dialog area
                const dialog = document.querySelector('ytcp-uploads-dialog');
                if (dialog) {
                    // Get all visible text spans that might contain status
                    const spans = dialog.querySelectorAll(
                        'span, .label, .message, [class*="text"], [class*="label"]'
                    );
                    for (const span of spans) {
                        const t = span.textContent.trim();
                        if (t && t.length > 3 && t.length < 300) {
                            parts.push(t);
                        }
                    }
                }

                return [...new Set(parts)].slice(0, 15).join(' | ');
            }""")
        except Exception:
            return "(could not read status)"

    def _extract_video_id(self) -> str:
        """Extract video ID from success dialog or page URL."""
        page = self._page

        try:
            link = page.locator(
                'a[href*="youtu.be"], a[href*="youtube.com/video"]'
            ).first
            href = link.get_attribute("href", timeout=5_000)
            if href and "youtu.be/" in href:
                return href.split("youtu.be/")[-1].split("?")[0]
            if href and "youtube.com/video/" in href:
                return href.split("youtube.com/video/")[-1].split("/")[0]
        except Exception:
            pass

        try:
            url = page.url
            if "/video/" in url:
                return url.split("/video/")[-1].split("/")[0]
        except Exception:
            pass

        return "unknown"

    def close_page(self) -> None:
        if self._page:
            self._page.close()
            self._page = None
