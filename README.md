# Instagram Watcher

[English] | [Polski](README.pl.md)

A robust Python CLI tool built on `yt-dlp`, `curl-cffi`, and `imageio-ffmpeg` to monitor public Instagram profiles and download new posts in maximum available quality without requiring an Instagram account.

## Download Directory Structure
All downloaded media files are automatically organized into structured subdirectories:
```text
downloads/<username>/
├── images/
│   ├── <shortcode>.jpg          # Single full-resolution photos
│   ├── <shortcode>_1.jpg        # Carousel/gallery slides (deduplicated)
│   └── <shortcode>_2.jpg
├── videos/
│   ├── <shortcode>.mp4          # Videos and Reels (video + merged DASH audio)
│   └── <shortcode>_1.mp4        # Video slides inside carousels
└── archive.txt                  # yt-dlp download archive for the profile
```

## Key Features & Architecture
- **Bypass Rate Limits (429) & Login Walls:** Uses `curl-cffi` with Chrome TLS impersonation to fetch data and metadata from public profiles anonymously.
- **Maximum Video & Audio Quality:** Instagram serves high-quality video and audio streams separately (DASH). With built-in `imageio-ffmpeg`, `yt-dlp` merges them into full-quality `.mp4` files.
- **Maximum Image Resolution:** Queries dedicated post endpoints (`/p/<shortcode>/`) to fetch original uncompressed assets, inspecting and logging resolution via `Pillow`.
- **Deduplication:** Carousel slides are cleanly saved once with numeric suffixes (`_1`, `_2`, etc.), preventing duplicated media.
- **Persistent State Tracking:** Tracks processed posts in `downloaded_posts.json` and `archive.txt` to avoid redundant requests and re-downloads.

## Installation

1. Activate your virtual environment:
   - Windows PowerShell:
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - Linux/macOS:
     ```bash
     source venv/bin/activate
     ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Show help and available options:
```powershell
python instagram_watcher.py --help
```

Download the latest posts from a profile (e.g. `nasa`):
```powershell
python instagram_watcher.py --profile nasa --limit 5
```

Download using a full URL:
```powershell
python instagram_watcher.py --profile https://www.instagram.com/nasa/ --limit 5
```

Run test suite:
```powershell
pytest
```
