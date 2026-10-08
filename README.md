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

## Important: Unauthenticated Mode & 12-Post Limit

Instagram enforces an aggressive **Login Wall** on public profiles:
- **Default Mode (No Account Required):** Without logging in, Instagram serves only the initial **12 latest posts** in the public page HTML. Any request for older posts (page 2+) without session credentials is intentionally rejected by Meta (`HTTP 401 / require_login`).
- **Why this is ideal for a Watcher:** For periodic monitoring (running on a schedule, e.g. daily or weekly), the 12-post limit is completely sufficient. Every newly published post appears at the very top of the grid and will be automatically detected and downloaded in full quality without requiring an account.
- **Deep Historical Archives (Optional):** If you ever need to download more than 12 historical posts at once from a profile, you can provide session cookies from any burner/dummy account via `--cookies`:
  ```powershell
  python instagram_watcher.py --profile nasa --limit 50 --cookies "sessionid=YOUR_SESSIONID"
  ```
  or via an exported Netscape cookies file:
  ```powershell
  python instagram_watcher.py --profile nasa --limit 50 --cookies cookies.txt
  ```

## CLI Arguments

| Argument | Description | Default |
| :--- | :--- | :--- |
| `--profile`, `-p` | Profile username or full URL (required) | *None* |
| `--limit`, `-l` | Number of latest new posts to download | `1` |
| `--download-dir` | Directory where media files are saved | `downloads` |
| `--db-file` | JSON file storing downloaded post IDs | `downloaded_posts.json` |
| `--page-delay` | Delay in seconds between pagination requests | `1.5` |
| `--cookies` | Optional session cookie string or path to `cookies.txt` | *None* |

## Tests

Run the full automated test suite:
```powershell
pytest -v
```

