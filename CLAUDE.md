# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python CLI tool that automates downloading Zoom cloud recordings and uploading them to YouTube via browser automation (Playwright). No APIs are used for Zoom/YouTube — both are driven through headless Chromium with persistent login sessions.

## Setup & Running

```bash
pip install -r requirements.txt
python -m playwright install chromium
cp config.example.yaml config.yaml   # then edit with your settings
```

```bash
python main.py                              # interactive mode
python main.py --date 2026-03-01            # specify date
python main.py --date 2026-03-01 -s 1       # auto-select first recording
python main.py --force-reupload             # skip duplicate confirmation
```

There are no tests or linting configured.

## Architecture

**Entry point:** `main.py` → calls `cli.run()`

**Core flow in `src/cli.py`:**
1. Parse CLI args and load YAML config
2. Launch a single persistent Playwright browser context (`browser_data/` stores session)
3. `ZoomClient` scrapes recording list, downloads MP4 to OS temp dir
4. `YouTubeClient` uploads via YouTube Studio UI with metadata/thumbnail/playlist
5. Log result to `uploads.json` (deduplication), clean up temp file

**Key modules:**
- `src/zoom_client.py` — Playwright automation for Zoom: login (credentials via OS keyring), list recordings, download MP4 with file validation (magic bytes check)
- `src/youtube_client.py` — Playwright automation for YouTube Studio: upload, set title/description/privacy/thumbnail/playlist, monitor progress, extract video ID
- `src/config_loader.py` — Loads and validates `config.yaml` into dataclasses
- `src/models.py` — Dataclasses: `ZoomRecording`, `UploadResult`, config types
- `src/utils.py` — Date parsing (`parse_date_input`) and formatting helpers

**Important design decisions:**
- Single shared Playwright browser context across both clients (one browser window)
- Zoom credentials stored in OS keyring, not config files
- Cross-platform keyboard handling (Cmd vs Ctrl) in YouTube client
- Debug screenshots saved on failures (`yt_debug_*.png`, `zoom_detail_debug.png`)
- `uploads.json` tracks upload history to prevent duplicate uploads
