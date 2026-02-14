# Zoom Recording to YouTube Uploader

CLI tool that downloads SIG Windows meeting recordings from Zoom and uploads them to YouTube with proper metadata.

## Setup

### 1. Install dependencies

```bash
cd D:\ai\zoom-youtube-uploader
pip install -r requirements.txt
python -m playwright install chromium
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

### First run

A Chromium browser window opens. You'll log into both Zoom and YouTube manually. Sessions are saved in `browser_data/` so you only log in once.

### Subsequent runs

The browser still opens (needed for Zoom download and YouTube upload) but logins are automatic from saved sessions.
