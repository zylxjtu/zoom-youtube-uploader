# Zoom Recording to YouTube Uploader

CLI tool that downloads SIG Windows meeting recordings from Zoom and uploads them to YouTube with proper metadata.

## Setup

### 1. Install dependencies

```bash
cd zoom-youtube-uploader
pip install -r requirements.txt
python -m playwright install chromium
```

**Linux/Ubuntu** — Playwright needs additional OS libraries. Install them with:

```bash
python -m playwright install-deps chromium
```

Keyring requires a secret service backend. On desktop Ubuntu (GNOME), `gnome-keyring` is usually pre-installed. On a headless server or WSL without a desktop environment, install the `keyrings.alt` package to use a file-based backend:

```bash
pip install keyrings.alt
```

### 2. Create config file

```bash
cp config.example.yaml config.yaml
```

Edit if you want to change playlist name, title format, or other defaults.

### 3. Add thumbnail (optional)

Place your thumbnail image in the project directory and set the filename in `config.yaml`:

```yaml
youtube:
  thumbnail_file: "thumbnail.png"
```

## Usage

```bash
python main.py
```

The tool will:

1. Open a browser window
2. Log in to Zoom (first run only — session is saved)
3. Ask for a meeting date
4. List recordings for that date
5. Let you pick a recording
6. Download the MP4
7. Log in to YouTube (first run only — session is saved)
8. Upload video with title/description/thumbnail/playlist
9. Print the YouTube video URL
10. Delete the downloaded MP4

## Authentication

### Zoom

- Credentials (email + password) are stored in your **OS keyring** (Windows Credential Manager / macOS Keychain / Linux keyring) under the service name `zoom-youtube-uploader`.
- On first run, if no credentials are found, the tool prompts you interactively and saves them to the keyring.
- During login, Playwright auto-fills email/password. If 2FA or CAPTCHA is required, the browser window pauses for you to complete login manually (5-minute timeout).

### YouTube

- No credentials are stored — YouTube/Google login is done **entirely manually** in the browser window. The tool navigates to YouTube Studio and waits if you need to sign in.

### Session Persistence

Both services share a **single persistent Chromium browser context** stored in the `browser_data/` directory. This directory holds cookies, localStorage, and other browser state — like a regular Chrome profile.

As long as `browser_data/` exists, both Zoom and YouTube sessions stay logged in via browser cookies:

- **Zoom**: Session cookies typically last ~2 weeks of inactivity, or expire immediately if you log out elsewhere.
- **YouTube/Google**: Sessions tend to last weeks to months, but Google may prompt re-auth after ~30 days, on suspicious activity, or after a password change.

Deleting `browser_data/` will require re-authentication for both services on the next run.

### First run

A Chromium browser window opens. You'll log into both Zoom and YouTube manually. Sessions are saved in `browser_data/` so you only log in once.

### Subsequent runs

The browser still opens (needed for Zoom download and YouTube upload) but logins are automatic from saved sessions.
