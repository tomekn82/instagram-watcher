"""
Instagram Watcher - Narzędzie CLI oparte na yt-dlp i curl-cffi do monitorowania
publicznego profilu Instagram i pobierania multimediów w maksymalnej dostępnej jakości.
Pliki są kategoryzowane do podfolderów 'images' oraz 'videos'.
"""

import argparse
import json
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from curl_cffi import requests
from PIL import Image
import yt_dlp

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("InstagramWatcher")


def get_ffmpeg_path() -> Optional[str]:
    """Zwraca ścieżkę do pliku wykonywalnego ffmpeg (z imageio_ffmpeg lub systemowego PATH)."""
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return shutil.which("ffmpeg")


def extract_username(profile_input: str) -> str:
    """Wyciąga czystą nazwę użytkownika z podanej nazwy lub pełnego URL."""
    cleaned = profile_input.strip()
    if "?" in cleaned:
        cleaned = cleaned.split("?")[0]
    if "#" in cleaned:
        cleaned = cleaned.split("#")[0]
    cleaned = cleaned.rstrip("/")
    if "/" in cleaned:
        cleaned = cleaned.split("/")[-1]
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    return cleaned


def load_downloaded_posts(db_path: Path) -> Set[str]:
    """Wczytuje zbiór pobranych identyfikatorów/shortcode'ów postów z pliku JSON."""
    if not db_path.is_file():
        return set()

    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(data)
            elif isinstance(data, dict):
                shortcodes = set()
                for key, val in data.items():
                    if isinstance(val, list):
                        shortcodes.update(val)
                    else:
                        shortcodes.add(key)
                return shortcodes
            return set()
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Nie udało się odczytać bazy {db_path} ({e}), tworzę nowy zbiór.")
        return set()


def save_downloaded_posts(db_path: Path, downloaded_ids: Set[str]) -> None:
    """Zapisuje zbiór pobranych identyfikatorów do pliku JSON."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = db_path.with_suffix(".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(downloaded_ids)), f, indent=2, ensure_ascii=False)
        temp_path.replace(db_path)
    except OSError as e:
        logger.error(f"Błąd zapisu do pliku {db_path}: {e}")
        if temp_path.exists():
            temp_path.unlink()


def fetch_profile_posts(username: str) -> List[Dict[str, Any]]:
    """Pobiera listę najnowszych postów z publicznego profilu Instagram."""
    url = f"https://www.instagram.com/{username}/"
    headers = {
        "Accept-Language": "en-US,en;q=0.9",
    }
    logger.info(f"Pobieranie osi czasu profilu: {url} ...")
    try:
        response = requests.get(url, impersonate="chrome", headers=headers, timeout=25)
    except Exception as e:
        logger.error(f"Błąd połączenia z Instagramem: {e}")
        return []

    if response.status_code == 404:
        logger.error(f"Profil '{username}' nie istnieje (HTTP 404).")
        return []
    elif response.status_code != 200:
        logger.error(f"Instagram zwrócił kod HTTP {response.status_code}.")
        return []

    html = response.text
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.DOTALL)

    def find_edges(obj: Any) -> Optional[List[Dict[str, Any]]]:
        if isinstance(obj, dict):
            if (
                "polaris_ordered_timeline_connection" in obj
                and "edges" in obj["polaris_ordered_timeline_connection"]
            ):
                return obj["polaris_ordered_timeline_connection"]["edges"]
            for v in obj.values():
                res = find_edges(v)
                if res is not None:
                    return res
        elif isinstance(obj, list):
            for item in obj:
                res = find_edges(item)
                if res is not None:
                    return res
        return None

    nodes: List[Dict[str, Any]] = []
    for s in scripts:
        if "polaris_ordered_timeline_connection" in s:
            try:
                data = json.loads(s)
                edges = find_edges(data)
                if edges:
                    for e in edges:
                        node = e.get("node")
                        if node and "code" in node:
                            nodes.append(node)
                    if nodes:
                        break
            except Exception:
                pass

    if not nodes:
        logger.debug("Próba odnalezienia postów za pomocą wyrażeń regularnych...")
        found_codes: List[str] = []
        for s in scripts:
            matches = re.findall(r'"code":"([A-Za-z0-9_-]{10,12})"', s)
            for c in matches:
                if c not in found_codes:
                    found_codes.append(c)
        for c in found_codes:
            nodes.append({"code": c, "media_type": 1})

    logger.info(f"Odnaleziono {len(nodes)} postów na profilu '{username}'.")
    return nodes


def fetch_post_details(shortcode: str) -> Optional[Dict[str, Any]]:
    """
    Pobiera pełne metadane posta z dedykowanego widoku https://www.instagram.com/p/<shortcode>/
    w celu uzyskania listy formatów o najwyższej rozdzielczości (image_versions2, display_resources, carousel_media).
    """
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    headers = {
        "Accept-Language": "en-US,en;q=0.9",
    }
    logger.info(f"Pobieranie szczegółowych metadanych z widoku posta: {post_url} ...")
    try:
        response = requests.get(post_url, impersonate="chrome", headers=headers, timeout=25)
    except Exception as e:
        logger.warning(f"Błąd połączenia podczas pobierania widoku posta {shortcode}: {e}")
        return None

    if response.status_code != 200:
        logger.warning(f"Widok posta {shortcode} zwrócił kod HTTP {response.status_code}.")
        return None

    html = response.text
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.DOTALL)

    def find_media(obj: Any) -> Optional[Dict[str, Any]]:
        if isinstance(obj, dict):
            if "xig_polaris_media" in obj:
                return obj["xig_polaris_media"]
            for v in obj.values():
                res = find_media(v)
                if res is not None:
                    return res
        elif isinstance(obj, list):
            for item in obj:
                res = find_media(item)
                if res is not None:
                    return res
        return None

    for s in scripts:
        if "xig_polaris_media" in s:
            try:
                data = json.loads(s)
                media = find_media(data)
                if media and "if_not_gated_logged_out" in media:
                    return media["if_not_gated_logged_out"]
            except Exception:
                pass

    return None


def select_best_image_url(media_dict: Dict[str, Any]) -> Optional[str]:
    """
    Wybiera URL obrazu o najwyższej dostępnej rozdzielczości z metadanych.
    Priorytet:
    1. candidates z image_versions2 (wybór najwyższej szerokości x wysokości lub nieprzeskalowanego oryginału)
    2. display_resources (sortowanie wg config_width * config_height)
    3. display_uri / display_url
    """
    candidates = media_dict.get("image_versions2", {}).get("candidates") or []
    if candidates:
        def candidate_score(cand: Dict[str, Any]) -> int:
            url = cand.get("url", "")
            w = cand.get("width")
            h = cand.get("height")
            if w and h:
                return int(w) * int(h)

            match = re.search(r"[ps](\d+)x(\d+)", url)
            if match:
                return int(match.group(1)) * int(match.group(2))

            orig_w = media_dict.get("original_width")
            orig_h = media_dict.get("original_height")
            if orig_w and orig_h:
                return int(orig_w) * int(orig_h)

            return 10**9

        best_cand = max(candidates, key=candidate_score)
        return best_cand.get("url")

    resources = media_dict.get("display_resources") or []
    if resources:
        def resource_score(res: Dict[str, Any]) -> int:
            w = res.get("config_width", 0)
            h = res.get("config_height", 0)
            return w * h

        best_res = max(resources, key=resource_score)
        return best_res.get("src") or best_res.get("url")

    return media_dict.get("display_uri") or media_dict.get("display_url")


def select_best_video_url(media_dict: Dict[str, Any]) -> Optional[str]:
    """Wybiera URL wideo o najwyższej rozdzielczości z video_versions."""
    video_versions = media_dict.get("video_versions") or []
    if video_versions:
        def video_score(v: Dict[str, Any]) -> int:
            w = v.get("width", 0)
            h = v.get("height", 0)
            return int(w) * int(h)

        best_v = max(video_versions, key=video_score)
        return best_v.get("url")
    return None


def download_file(url: str, output_path: Path) -> bool:
    """Pobiera plik z podanego URL i zapisuje pod wskazaną ścieżką."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, impersonate="chrome", timeout=40)
        if r.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(r.content)
            return True
        logger.error(f"Nie udało się pobrać pliku {output_path.name} (HTTP {r.status_code})")
        return False
    except Exception as e:
        logger.error(f"Błąd zapisu pliku {output_path.name}: {e}")
        return False


def download_image_and_log_dimensions(url: str, output_path: Path) -> bool:
    """Pobiera obraz z podanego URL i loguje jego rzeczywiste wymiary w pikselach za pomocą Pillow."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, impersonate="chrome", timeout=30)
        if r.status_code != 200:
            logger.error(f"Nie udało się pobrać obrazu z {url[:80]}... (HTTP {r.status_code})")
            return False

        with open(output_path, "wb") as f:
            f.write(r.content)

        file_size_kb = len(r.content) / 1024

        try:
            with Image.open(output_path) as img:
                width, height = img.size
            logger.info(
                f"Zapisano pełnowymiarowy obraz 'images/{output_path.name}': "
                f"rozdzielczość: {width}x{height} px, rozmiar: {file_size_kb:.1f} KB"
            )
        except Exception as e:
            logger.info(
                f"Zapisano obraz 'images/{output_path.name}' ({file_size_kb:.1f} KB), "
                f"nie udało się odczytać wymiarów: {e}"
            )

        return True
    except Exception as e:
        logger.error(f"Błąd podczas zapisu obrazu {output_path.name}: {e}")
        return False


def download_post_media(
    node: Dict[str, Any],
    profile_name: str,
    images_dir: Path,
    videos_dir: Path,
    archive_path: Path,
) -> bool:
    """
    Pobiera multimedia dla danego posta w najwyższej dostępnej jakości:
      - Obrazy zapisywane są do folderu 'images/'.
      - Wideo zapisywane są do folderu 'videos/'.
    Dla karuzeli (galerii):
      - Zapisuje elementy wyłącznie jako {code}_1.ext, {code}_2.ext ... (bez podwójnych kopii).
    Dla pojedynczych postów:
      - Zapisuje plik jako {code}.ext w odpowiednim podkatalogu.
    """
    code = node["code"]
    media_type = node.get("media_type")  # 1: image, 2: video, 8: carousel
    post_url = f"https://www.instagram.com/p/{code}/"

    images_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)
    downloaded = False

    # Pobierz dedykowane metadane posta dla maksymalnej jakości
    post_details = fetch_post_details(code) or node
    carousel_media = post_details.get("carousel_media") or []

    # 1. Obsługa karuzeli (galerii wieloelementowej)
    if len(carousel_media) > 1:
        logger.info(
            f"Post {code} to karuzela ({len(carousel_media)} elementów). "
            f"Pobieranie slajdów w pełnej rozdzielczości..."
        )
        carousel_success = False
        for idx, item in enumerate(carousel_media, start=1):
            is_slide_video = item.get("is_video") or bool(item.get("video_versions"))
            if is_slide_video:
                best_video_url = select_best_video_url(item)
                if best_video_url:
                    out_file = videos_dir / f"{code}_{idx}.mp4"
                    if download_file(best_video_url, out_file):
                        carousel_success = True
                        file_size_kb = out_file.stat().st_size / 1024
                        logger.info(f"Zapisano wideo 'videos/{out_file.name}' ({file_size_kb:.1f} KB)")
            else:
                best_img_url = select_best_image_url(item)
                if best_img_url:
                    out_file = images_dir / f"{code}_{idx}.jpg"
                    if download_image_and_log_dimensions(best_img_url, out_file):
                        carousel_success = True

        if carousel_success:
            downloaded = True
            with open(archive_path, "a", encoding="utf-8") as f:
                f.write(f"instagram {code}\n")

    # 2. Obsługa pojedynczego wideo
    is_single_video = not downloaded and (media_type == 2 or bool(post_details.get("video_versions")))
    if is_single_video:
        ffmpeg_path = get_ffmpeg_path()
        logger.info(f"Pobieranie wideo w maksymalnej jakości przez yt-dlp ({post_url})...")

        ydl_opts: Dict[str, Any] = {
            "outtmpl": str(videos_dir / f"{code}.%(ext)s"),
            "download_archive": str(archive_path),
            "format_sort": ["res", "fps", "size", "br"],
            "quiet": False,
            "no_warnings": True,
        }

        if ffmpeg_path:
            ydl_opts["ffmpeg_location"] = ffmpeg_path
            ydl_opts["format"] = "bestvideo+bestaudio/best"
        else:
            logger.warning("Brak ffmpeg w systemie – wybieram zintegrowany format wideo.")
            ydl_opts["format"] = "b[vcodec!=none][acodec!=none]/best[ext=mp4]/best"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ret = ydl.download([post_url])
                if ret == 0:
                    downloaded = True
                    logger.info(f"Pomyślnie pobrano wideo 'videos/{code}.mp4'.")
        except Exception as e:
            logger.warning(f"yt-dlp napotkał problem przy {code}: {e}")
            try:
                fallback_opts = {
                    "outtmpl": str(videos_dir / f"{code}.%(ext)s"),
                    "download_archive": str(archive_path),
                    "format": "b[vcodec!=none][acodec!=none]/best[ext=mp4]/best",
                    "quiet": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                    ret = ydl.download([post_url])
                    if ret == 0:
                        downloaded = True
                        logger.info(f"Pomyślnie pobrano wideo {code} za pomocą formatu awaryjnego.")
            except Exception as e2:
                logger.error(f"Nie udało się pobrać wideo {code} w trybie awaryjnym: {e2}")

    # 3. Obsługa pojedynczego zdjęcia (lub karuzeli 1-elementowej)
    if not downloaded:
        item_data = carousel_media[0] if carousel_media else post_details
        best_img_url = select_best_image_url(item_data)
        if best_img_url:
            out_file = images_dir / f"{code}.jpg"
            if download_image_and_log_dimensions(best_img_url, out_file):
                downloaded = True
                with open(archive_path, "a", encoding="utf-8") as f:
                    f.write(f"instagram {code}\n")

    return downloaded


def watch_profile(
    profile_input: str,
    limit: int = 1,
    download_dir: Path = Path("downloads"),
    db_path: Path = Path("downloaded_posts.json"),
) -> int:
    """Monitoruje profil, sprawdza historię i pobiera do N nowych multimediów w podfolderach images/ i videos/."""
    username = extract_username(profile_input)
    target_dir = download_dir / username
    images_dir = target_dir / "images"
    videos_dir = target_dir / "videos"
    archive_path = target_dir / "archive.txt"

    images_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)

    downloaded_ids = load_downloaded_posts(db_path)
    logger.info(f"Wczytano {len(downloaded_ids)} wcześniej pobranych postów z {db_path}")

    nodes = fetch_profile_posts(username)
    if not nodes:
        logger.warning(f"Brak postów do przetworzenia dla profilu '{username}'.")
        return 0

    posts_checked = 0
    posts_downloaded = 0

    for node in nodes:
        if limit > 0 and posts_downloaded >= limit:
            logger.info(f"Osiągnięto limit nowo pobranych multimediów ({limit}).")
            break

        posts_checked += 1
        code = node["code"]

        if code in downloaded_ids:
            logger.info(f"[{posts_checked}] Post {code} był już pobrany - pomijam.")
            continue

        logger.info(f"[{posts_checked}] Przetwarzanie nowego postu: {code} ...")
        success = download_post_media(node, username, images_dir, videos_dir, archive_path)
        if success:
            downloaded_ids.add(code)
            save_downloaded_posts(db_path, downloaded_ids)
            posts_downloaded += 1
            logger.info(f"Pomyślnie zapisano post {code}.")
        else:
            logger.warning(f"Nie udało się zapisać multimediów dla postu {code}.")

    logger.info(
        f"Zakończono. Sprawdzono postów: {posts_checked}, nowo pobranych: {posts_downloaded}."
    )
    return posts_downloaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitoruj publiczny profil na Instagramie i pobieraj multimedia do podfolderów images/ i videos/."
    )
    parser.add_argument(
        "--profile",
        "-p",
        required=True,
        type=str,
        help="Nazwa profilu lub pełny URL profilu na Instagramie (np. 'nasa' lub 'https://www.instagram.com/nasa/').",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=1,
        help="Liczba najnowszych multimediów do pobrania (domyślnie: 1).",
    )
    parser.add_argument(
        "--download-dir",
        type=str,
        default="downloads",
        help="Katalog docelowy dla pobranych multimediów (domyślnie: 'downloads').",
    )
    parser.add_argument(
        "--db-file",
        type=str,
        default="downloaded_posts.json",
        help="Ścieżka do pliku bazy pobranych postów JSON (domyślnie: 'downloaded_posts.json').",
    )

    args = parser.parse_args()

    if args.limit < 1:
        parser.error("Wartość parametru --limit musi być większa od zera.")

    return args


def main():
    args = parse_args()
    watch_profile(
        profile_input=args.profile,
        limit=args.limit,
        download_dir=Path(args.download_dir),
        db_path=Path(args.db_file),
    )


if __name__ == "__main__":
    main()
