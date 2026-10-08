# Instagram Watcher

[English] | [Polski](README.pl.md)

A robust Python CLI tool built on `yt-dlp`, `curl-cffi`, and `imageio-ffmpeg` to monitor Instagram profiles and download posts (photos, carousels, videos, Reels) in maximum available quality.

---

## Two Operating Modes

The program supports two distinct modes of operation depending on whether authentication cookies are provided:

```
┌────────────────────────────────────────────────────────────────────────┐
│  Mode 1: Anonymous / No-Login (Default)                                │
│  • No Instagram account or login required                              │
│  • Maximum 12 latest posts per run (Instagram public grid limit)       │
│  • Ideal for scheduled watchers (cron / periodic monitoring)           │
│  • Command: python instagram_watcher.py -p <user> --limit 5            │
├────────────────────────────────────────────────────────────────────────┤
│  Mode 2: Authenticated / With Cookies (--cookies)                      │
│  • Removes the 12-post limit completely                                │
│  • Full cursor-based GraphQL pagination (12, 50, 200+ posts)           │
│  • Ideal for deep historical backups & large archives                  │
│  • Command: python instagram_watcher.py -p <user> -l 50 --cookies ...  │
└────────────────────────────────────────────────────────────────────────┘
```

### 1. Anonymous Mode (Default — No Account Needed)
* **How it works:** Directly accesses public profile timelines using Chrome TLS fingerprint impersonation (`curl-cffi`).
* **12-Post Limitation:** Instagram's architecture only pre-renders the initial **12 posts** (Page 1) in the public HTML. Any unauthenticated request for older posts (Page 2+) is blocked by Meta's login wall (`HTTP 401 / require_login`).
* **Why it is ideal for a Watcher:** When running periodically (e.g. daily or weekly via cron/Task Scheduler), newly published posts always appear at the top of the grid. The watcher automatically detects and downloads new media without ever risking an account ban or needing credentials.

### 2. Authenticated Mode (`--cookies`)
* **How it works:** Uses session credentials to query Instagram's internal Relay GraphQL endpoint (`PolarisProfilePostsTabContentQuery_connection`).
* **No Post Limit:** Automatically traverses pagination cursors (`end_cursor`, `has_next_page`) across multiple pages to fetch deep post history (tens, hundreds, or thousands of posts).
* **Rate-Limit Safe:** Includes configurable delays (`--page-delay`, default 1.5s) between pagination batches to avoid account rate-limiting.
* **Format:** Supports standard Netscape `cookies.txt` files (exported from your browser) or inline session strings (`"sessionid=..."`).

---

## Download Directory Structure

All downloaded media files are organized into cleanly separated subdirectories:

```text
downloads/<username>/
├── images/
│   ├── <shortcode>.jpg          # Single full-resolution photos
│   ├── <shortcode>_1.jpg        # Carousel / gallery slides (deduplicated)
│   └── <shortcode>_2.jpg
├── videos/
│   ├── <shortcode>.mp4          # Videos and Reels (video + merged DASH audio)
│   └── <shortcode>_1.mp4        # Video slides inside carousels
└── archive.txt                  # yt-dlp download archive for the profile
```

---

## Key Features & Architecture

- **Bypass Rate Limits (429) & Login Walls:** Uses `curl-cffi` with Chrome TLS impersonation to query endpoints without triggering automated bot detection.
- **Maximum Video & Audio Quality:** Instagram serves high-quality video and audio streams separately (DASH). With built-in `imageio-ffmpeg`, `yt-dlp` automatically merges them into full-quality `.mp4` files.
- **Maximum Image Resolution:** Queries dedicated post metadata and candidate matrices, downloading original uncompressed assets and verifying dimensions via `Pillow` (e.g. 3024x4032 px).
- **Deduplication:** Carousel items are saved with numbered suffixes (`_1`, `_2`), avoiding redundant or duplicate downloads.
- **Persistent State Tracking:** Records processed shortcodes in `downloaded_posts.json` and `archive.txt`. The watcher immediately stops upon encountering previously downloaded posts, minimizing network overhead.

---

## Installation

1. **Activate virtual environment:**
   - Windows PowerShell:
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - Linux/macOS:
     ```bash
     source venv/bin/activate
     ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

---

## Usage Examples

### 1. Anonymous Monitoring (Up to 12 posts)

Download the 5 newest posts from a profile without logging in:
```powershell
python instagram_watcher.py --profile nasa --limit 5
```

Download using a full URL:
```powershell
python instagram_watcher.py --profile https://www.instagram.com/nasa/ --limit 12
```

### 2. Large Archive Download with Cookies (12+ posts)

Using an exported Netscape `cookies.txt` file:
```powershell
python instagram_watcher.py --profile corinavitor --limit 50 --cookies cookies.txt
```

Using a session ID token directly:
```powershell
python instagram_watcher.py --profile corinavitor --limit 100 --cookies "sessionid=YOUR_SESSION_ID"
```

Adjusting the pagination delay (e.g. 2 seconds):
```powershell
python instagram_watcher.py --profile corinavitor --limit 150 --cookies cookies.txt --page-delay 2.0
```

> [!TIP]
> **How to obtain `cookies.txt`:** Install a browser extension such as *Get cookies.txt LOCALLY* (Chrome/Firefox/Edge), log into Instagram, and export cookies for `instagram.com` to `cookies.txt` in the project directory. The file is automatically ignored by `.gitignore`.

---

## CLI Arguments

| Argument | Short | Description | Default |
| :--- | :--- | :--- | :--- |
| `--profile` | `-p` | Profile username or full URL (required) | *None* |
| `--limit` | `-l` | Number of latest new posts to download | `1` |
| `--download-dir` | | Directory where media files are saved | `downloads` |
| `--db-file` | | JSON file storing downloaded post IDs | `downloaded_posts.json` |
| `--page-delay` | | Delay in seconds between pagination requests | `1.5` |
| `--cookies` | | Optional session cookie string or path to `cookies.txt` | *None* |

---

## Tests

Run the full automated test suite (18 unit tests):
```powershell
pytest -v
```
