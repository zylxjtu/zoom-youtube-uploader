from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from .config_loader import load_config
from .models import ZoomRecording
from .utils import format_date_for_title, parse_date_input
from .zoom_client import ZoomClient
from .youtube_client import YouTubeClient

console = Console()

BROWSER_DATA_DIR = "browser_data"
UPLOAD_LOG = "uploads.json"


def _load_upload_log() -> dict:
    path = Path(UPLOAD_LOG)
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_upload_log(log: dict) -> None:
    Path(UPLOAD_LOG).write_text(json.dumps(log, indent=2))


def _prompt_date() -> date:
    """Prompt user for a meeting date."""
    text = Prompt.ask(
        "Meeting date",
        default="today",
    )
    try:
        return parse_date_input(text)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)


def _display_recordings(recordings: list[ZoomRecording]) -> None:
    """Display a rich table of Zoom recordings."""
    table = Table(title="Zoom Recordings")
    table.add_column("#", style="dim", width=3)
    table.add_column("Topic")
    table.add_column("Date")
    table.add_column("Duration")

    for i, r in enumerate(recordings, 1):
        table.add_row(str(i), r.topic, r.date, r.duration)

    console.print(table)


def _select_recording(recordings: list[ZoomRecording]) -> int:
    """Let user select a recording, auto-select if only one. Returns index."""
    if len(recordings) == 1:
        console.print(f"Auto-selected: [bold]{recordings[0].topic}[/bold]")
        return 0

    idx = IntPrompt.ask(
        "Select recording number",
        default=1,
    )
    if idx < 1 or idx > len(recordings):
        console.print("[red]Invalid selection.[/red]")
        sys.exit(1)
    return idx - 1


def run() -> None:
    """Main CLI flow."""
    console.print("[bold]Zoom Recording → YouTube Uploader[/bold]\n")

    # 1. Load config
    config = load_config()

    # 2. Prompt for date
    recording_date = _prompt_date()
    console.print(f"Looking up recordings for: [cyan]{recording_date.isoformat()}[/cyan]\n")

    # 3. Launch browser (shared by Zoom and YouTube)
    pw = sync_playwright().start()
    # Always headed — user may need to log in to either Zoom or YouTube
    context = pw.chromium.launch_persistent_context(
        user_data_dir=BROWSER_DATA_DIR,
        headless=False,
        viewport={"width": 1280, "height": 900},
        accept_downloads=True,
        timeout=120_000,  # 2 min default for all actions
        args=[
            "--disable-blink-features=AutomationControlled",
        ],
        ignore_default_args=["--enable-automation"],
    )

    try:
        # 4. Zoom: log in and list recordings
        zoom = ZoomClient(context)
        with console.status("Connecting to Zoom..."):
            zoom.ensure_logged_in()
        console.print("[green]Zoom ready.[/green]\n")

        with console.status("Fetching recordings..."):
            try:
                recordings = zoom.list_recordings(recording_date)
            except Exception as e:
                console.print(f"[red]Failed to fetch recordings: {e}[/red]")
                sys.exit(1)

        if not recordings:
            console.print("[yellow]No recordings found for this date.[/yellow]")
            sys.exit(0)

        # 5. Select recording
        if len(recordings) == 1:
            selected = recordings[0]
            console.print(f"Found: [bold]{selected.topic}[/bold] ({selected.date})")
        else:
            _display_recordings(recordings)
            console.print()
            selected = recordings[_select_recording(recordings)]

        title = config.defaults.title_format.format(
            date=format_date_for_title(recording_date)
        )

        # 6. Check if already uploaded
        upload_log = _load_upload_log()
        if title in upload_log:
            prev = upload_log[title]
            console.print(f"[yellow]Already uploaded: {prev}[/yellow]")
            if not Confirm.ask("Upload again?", default=False):
                console.print("Aborted.")
                sys.exit(0)

        # 7. Download MP4 from Zoom
        filename = f"{title.replace(' ', '_')}.mp4"
        dest_path = Path(tempfile.gettempdir()) / filename

        if dest_path.exists():
            console.print(f"[yellow]File already exists: {dest_path} — skipping download.[/yellow]")
        else:
            console.print()
            with console.status("Downloading recording (watch browser)..."):
                try:
                    zoom.download_recording(
                        selected,
                        dest_path,
                    )
                except Exception as e:
                    console.print(f"\n[red]Download failed: {e}[/red]")
                    sys.exit(1)
            console.print(f"[green]Downloaded:[/green] {dest_path}")

        zoom.close_page()

        # 8. YouTube: log in
        console.print()
        yt = YouTubeClient(context)
        with console.status("Connecting to YouTube Studio..."):
            yt.ensure_logged_in()
        console.print("[green]YouTube Studio ready.[/green]")

        # 9. Upload video (includes thumbnail + playlist)
        console.print()
        with console.status("Uploading to YouTube (watch browser for progress)..."):
            try:
                result = yt.upload_video(
                    file_path=dest_path,
                    title=title,
                    description=config.defaults.description,
                    privacy_status=config.defaults.privacy_status,
                    made_for_kids=config.defaults.made_for_kids,
                    thumbnail_file=config.youtube.thumbnail_file or None,
                    playlist_name=config.youtube.playlist_name or None,
                )
            except Exception as e:
                console.print(f"\n[red]Upload failed: {e}[/red]")
                sys.exit(1)

        # 10. Print result and save to log
        console.print()
        upload_log[title] = result.url
        _save_upload_log(upload_log)

        if result.video_id != "unknown":
            console.print(f"[bold green]Done! Video URL: {result.url}[/bold green]")
        else:
            console.print(
                "[bold yellow]Upload completed but could not extract video URL. "
                "Check YouTube Studio.[/bold yellow]"
            )

        yt.close_page()

    finally:
        context.close()
        pw.stop()

    # 11. Cleanup
    dest_path.unlink()
    console.print(f"Cleaned up {dest_path}")
