"""
Instagram Watcher - CLI tool powered by yt-dlp and curl-cffi to monitor
a public Instagram profile and download media in maximum available quality.
Files are categorized into 'images' and 'videos' subdirectories.
"""

import argparse
import http.cookiejar
import json
import logging
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from curl_cffi import requests
from PIL import Image
import yt_dlp

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("InstagramWatcher")


def get_ffmpeg_path() -> Optional[str]:
    """Return path to ffmpeg executable (from imageio_ffmpeg or system PATH)."""
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return shutil.which("ffmpeg")


def extract_username(profile_input: str) -> str:
    """Extract clean username from a handle or full profile URL."""
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
    """Load the set of downloaded post shortcodes/IDs from a JSON file."""
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
        logger.warning(f"Could not read database {db_path} ({e}), initializing empty set.")
        return set()


def save_downloaded_posts(db_path: Path, downloaded_ids: Set[str]) -> None:
    """Save the set of downloaded post IDs to a JSON file atomically."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = db_path.with_suffix(".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(downloaded_ids)), f, indent=2, ensure_ascii=False)
        temp_path.replace(db_path)
    except OSError as e:
        logger.error(f"Error saving to file {db_path}: {e}")
        if temp_path.exists():
            temp_path.unlink()


def load_cookies_into_session(session: requests.Session, cookies_input: str) -> None:
    """Load cookies from a Netscape cookiejar file or header string into the session."""
    raw_input = cookies_input.strip().strip("'\"")
    cookie_path = Path(raw_input)
    if cookie_path.is_file():
        cj = http.cookiejar.MozillaCookieJar(str(cookie_path))
        try:
            cj.load(ignore_discard=True, ignore_expires=True)
            for cookie in cj:
                session.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
            logger.info(f"Loaded cookies from file '{cookie_path}'.")
            return
        except Exception as e:
            logger.warning(f"Could not parse '{cookie_path}' as MozillaCookieJar: {e}. Trying raw string parsing.")
            try:
                content = cookie_path.read_text(encoding="utf-8")
            except Exception:
                content = ""
    else:
        content = raw_input

    # If raw sessionid token was provided directly (no '=' sign)
    if "=" not in content and len(content) > 10:
        session.cookies.set("sessionid", content, domain=".instagram.com")
        logger.info("Loaded sessionid cookie from raw token string.")
        return

    loaded_count = 0
    for item in content.split(";"):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            session.cookies.set(k.strip(), v.strip(), domain=".instagram.com")
            loaded_count += 1
    if loaded_count > 0:
        logger.info(f"Loaded {loaded_count} cookie(s) into session.")


def find_edges_and_page_info(obj: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Recursively extract post nodes and page_info (end_cursor, has_next_page) from
    Instagram GraphQL or REST JSON structures.
    """
    nodes: List[Dict[str, Any]] = []
    page_info: Dict[str, Any] = {}

    if isinstance(obj, dict):
        # 1. Check known timeline connection keys
        for key in (
            "polaris_ordered_timeline_connection",
            "edge_owner_to_timeline_media",
            "xdt_api__v1__feed__user_timeline_graphql_connection",
            "xdt_get_owner_to_timeline_media_logged_out",
        ):
            if key in obj and isinstance(obj[key], dict):
                conn = obj[key]
                if "edges" in conn and isinstance(conn["edges"], list):
                    for edge in conn["edges"]:
                        node = edge.get("node") if isinstance(edge, dict) else None
                        if node and ("code" in node or "shortcode" in node):
                            if "code" not in node and "shortcode" in node:
                                node["code"] = node["shortcode"]
                            nodes.append(node)
                    if "page_info" in conn and isinstance(conn["page_info"], dict):
                        page_info = conn["page_info"]
                    if nodes:
                        return nodes, page_info

        # 2. Check if dict directly represents a connection with 'edges' and 'page_info'
        if "edges" in obj and isinstance(obj["edges"], list) and "page_info" in obj:
            for edge in obj["edges"]:
                node = edge.get("node") if isinstance(edge, dict) else None
                if node and ("code" in node or "shortcode" in node):
                    if "code" not in node and "shortcode" in node:
                        node["code"] = node["shortcode"]
                    nodes.append(node)
            pi = obj.get("page_info")
            if isinstance(pi, dict):
                page_info = pi
            if nodes:
                return nodes, page_info

        # 3. Check REST API format ('items', 'more_available', 'next_max_id')
        if "items" in obj and isinstance(obj["items"], list):
            for item in obj["items"]:
                if isinstance(item, dict) and ("code" in item or "shortcode" in item or "pk" in item):
                    if "code" not in item and "shortcode" in item:
                        item["code"] = item["shortcode"]
                    nodes.append(item)
            page_info = {
                "has_next_page": bool(obj.get("more_available", False)),
                "end_cursor": obj.get("next_max_id"),
            }
            if nodes:
                return nodes, page_info

        # Recurse into dict values
        for v in obj.values():
            if isinstance(v, (dict, list)):
                sub_nodes, sub_pi = find_edges_and_page_info(v)
                if sub_nodes:
                    return sub_nodes, sub_pi

    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                sub_nodes, sub_pi = find_edges_and_page_info(item)
                if sub_nodes:
                    return sub_nodes, sub_pi

    return nodes, page_info


def fetch_profile_posts_page_graphql(
    session: requests.Session,
    username: str,
    user_id: Optional[str],
    end_cursor: str,
    csrf_token: str,
    lsd_token: str,
    app_id: str = "936619743392459",
    user_pk: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Fetch the next batch of posts using Instagram GraphQL endpoint with cursor pagination.
    """
    graphql_url = "https://www.instagram.com/graphql/query/"
    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": csrf_token or session.cookies.get("csrftoken", ""),
        "X-IG-App-ID": app_id,
        "X-ASBD-ID": "129477",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/{username}/",
        "Origin": "https://www.instagram.com",
    }
    if lsd_token:
        headers["X-FB-LSD"] = lsd_token

    target_id = user_pk or user_id or username

    # Query variations
    query_attempts = [
        (
            "28142289515441884",
            "PolarisProfilePostsTabContentQuery_connection",
            {"after": end_cursor, "first": 12, "username": username},
        ),
        (
            "27389614800735091",
            "PolarisLoggedOutDesktopWWWProfilePostsTabContentQuery_connection",
            {"after": end_cursor, "first": 12, "id": target_id},
        ),
        (
            "28816028924680412",
            "PolarisOwnerToTimelineMediaLoggedOutQuery_connection",
            {"after": end_cursor, "first": 12, "owner_id": target_id},
        ),
        (
            "27553725110923321",
            "PolarisLoggedOutDesktopWWWProfilePostsTabContentQuery",
            {"after": end_cursor, "first": 12, "username": username},
        ),
    ]

    auth_blocked = False

    for doc_id, friendly_name, variables in query_attempts:
        req_headers = dict(headers)
        req_headers["X-FB-Friendly-Name"] = friendly_name
        data = {
            "variables": json.dumps(variables),
            "doc_id": doc_id,
        }
        if lsd_token:
            data["lsd"] = lsd_token

        try:
            resp = session.post(graphql_url, data=data, headers=req_headers, impersonate="chrome", timeout=25)
            if resp.status_code == 401 or (resp.status_code == 200 and '"require_login":true' in resp.text):
                auth_blocked = True
            elif resp.status_code == 200:
                resp_json = resp.json()
                nodes, page_info = find_edges_and_page_info(resp_json)
                if nodes:
                    logger.debug(f"GraphQL query {friendly_name} succeeded with {len(nodes)} nodes.")
                    return nodes, page_info
        except Exception as e:
            logger.debug(f"GraphQL attempt {friendly_name} failed: {e}")

    # Fallback to query_hash GET queries
    fallback_query_hashes = ["69cba40317214236af40e7efa697781d", "42323d64886122307be10013ad2dcc44"]
    for qh in fallback_query_hashes:
        try:
            vars_json = json.dumps({"id": target_id, "first": 12, "after": end_cursor})
            get_params = {"query_hash": qh, "variables": vars_json}
            resp = session.get(graphql_url, params=get_params, headers=headers, impersonate="chrome", timeout=25)
            if resp.status_code == 401 or (resp.status_code == 200 and '"require_login":true' in resp.text):
                auth_blocked = True
            elif resp.status_code == 200:
                resp_json = resp.json()
                nodes, page_info = find_edges_and_page_info(resp_json)
                if nodes:
                    logger.debug(f"GraphQL query_hash {qh} succeeded with {len(nodes)} nodes.")
                    return nodes, page_info
        except Exception as e:
            logger.debug(f"GraphQL query_hash attempt {qh} failed: {e}")

    # Fallback to REST feed endpoint
    if target_id:
        try:
            rest_url = f"https://www.instagram.com/api/v1/feed/user/{target_id}/"
            resp = session.get(rest_url, params={"count": 12, "max_id": end_cursor}, headers=headers, impersonate="chrome", timeout=25)
            if resp.status_code == 401 or '"require_login":true' in resp.text:
                auth_blocked = True
            elif resp.status_code == 200:
                resp_json = resp.json()
                nodes, page_info = find_edges_and_page_info(resp_json)
                if nodes:
                    logger.debug(f"REST feed endpoint succeeded with {len(nodes)} nodes.")
                    return nodes, page_info
        except Exception as e:
            logger.debug(f"REST feed endpoint attempt failed: {e}")

    if auth_blocked or not session.cookies.get("sessionid"):
        logger.warning(
            "Instagram zablokowal pobranie kolejnej strony postow (wymagana autoryzacja HTTP 401 / require_login).\n"
            "   Dla sesji niezalogowanych Instagram ogranicza dostep do pierwszych 12 postow profilu.\n"
            "   Aby pobrac wiecej postow (ponad 12), przekaz ciasteczka zalogowanej sesji za pomoca parametru:\n"
            "      --cookies \"sessionid=TWOJ_SESSIONID\"\n"
            "   lub wskaz plik cookies wyeksportowany z przegladarki:\n"
            "      --cookies cookies.txt"
        )

    return [], {}


def iterate_profile_posts(
    username: str,
    limit: int = 1,
    page_delay: float = 1.5,
    session: Optional[requests.Session] = None,
    cookies_path: Optional[str] = None,
) -> Iterator[Dict[str, Any]]:
    """
    Generator yielding post nodes from a public Instagram profile page by page.
    Handles cursor pagination (end_cursor / has_next_page) via GraphQL queries.
    Introduces a configurable delay between page requests to avoid rate limits.
    """
    if session is None:
        session = requests.Session()
    if cookies_path:
        load_cookies_into_session(session, cookies_path)

    profile_url = f"https://www.instagram.com/{username}/"
    headers = {
        "Accept-Language": "en-US,en;q=0.9",
    }
    logger.info(f"Fetching profile timeline: {profile_url} ...")
    try:
        response = session.get(profile_url, impersonate="chrome", headers=headers, timeout=25)
    except Exception as e:
        logger.error(f"Connection error while fetching Instagram profile: {e}")
        return

    if response.status_code == 404:
        logger.error(f"Profile '{username}' does not exist (HTTP 404).")
        return
    elif response.status_code != 200:
        logger.error(f"Instagram returned HTTP {response.status_code}.")
        return

    html = response.text
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.DOTALL)

    nodes: List[Dict[str, Any]] = []
    page_info: Dict[str, Any] = {}
    user_id: Optional[str] = None
    user_pk: Optional[str] = None

    # Search for user pk using regex directly from profile html
    pk_match = (
        re.search(r'"user":\{"pk":"(\d+)"[^}]*"username":"' + re.escape(username) + r'"', html)
        or re.search(r'"pk":"(\d+)"[^}]*"username":"' + re.escape(username) + r'"', html)
        or re.search(r'"username":"' + re.escape(username) + r'"[^}]*"pk":"(\d+)"', html)
    )
    if pk_match:
        user_pk = pk_match.group(1)

    for s in scripts:
        if "polaris_ordered_timeline_connection" in s or "xig_user_by_username" in s:
            try:
                data = json.loads(s)
                found_nodes, found_pi = find_edges_and_page_info(data)
                if found_nodes:
                    nodes = found_nodes
                    page_info = found_pi

                    def find_user_ids(obj: Any) -> Tuple[Optional[str], Optional[str]]:
                        if isinstance(obj, dict):
                            if "xig_user_by_username" in obj and isinstance(obj["xig_user_by_username"], dict):
                                u = obj["xig_user_by_username"]
                                return u.get("pk"), u.get("id")
                            if "pk" in obj and "polaris_ordered_timeline_connection" in obj:
                                return obj.get("pk"), obj.get("id")
                            for v in obj.values():
                                p, i = find_user_ids(v)
                                if p or i:
                                    return p, i
                        elif isinstance(obj, list):
                            for item in obj:
                                p, i = find_user_ids(item)
                                if p or i:
                                    return p, i
                        return None, None

                    found_pk, found_id = find_user_ids(data)
                    if found_pk:
                        user_pk = str(found_pk)
                    if found_id:
                        user_id = str(found_id)
                    break
            except Exception:
                pass

    if not nodes:
        logger.debug("Falling back to regex extraction for post codes...")
        found_codes: List[str] = []
        for s in scripts:
            matches = re.findall(r'"code":"([A-Za-z0-9_-]{10,12})"', s)
            for c in matches:
                if c not in found_codes:
                    found_codes.append(c)
        for c in found_codes:
            nodes.append({"code": c, "media_type": 1})

    # If no nodes discovered, try yt-dlp playlist extraction fallback
    if not nodes:
        logger.debug("Attempting fallback post discovery via yt-dlp...")
        try:
            ydl_opts = {
                "extract_flat": True,
                "playlistend": limit if limit > 0 else None,
                "quiet": True,
                "no_warnings": True,
            }
            if cookies_path and Path(cookies_path).is_file():
                ydl_opts["cookiefile"] = str(cookies_path)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(profile_url, download=False)
                if info and "entries" in info:
                    for entry in info["entries"]:
                        if entry and "id" in entry:
                            nodes.append({"code": entry["id"], "media_type": 1})
        except Exception as e:
            logger.debug(f"yt-dlp fallback extraction not available: {e}")

    logger.info(f"Page 1: discovered {len(nodes)} posts on profile '{username}'.")

    csrf_token = session.cookies.get("csrftoken", "")
    lsd_match = re.search(r'"LSD",\[\],\{"token":"([^"]+)"\}', html)
    lsd_token = lsd_match.group(1) if lsd_match else ""
    app_id_match = re.search(r'"appId":"(\d+)"', html) or re.search(r'"APP_ID":"(\d+)"', html)
    app_id = app_id_match.group(1) if app_id_match else "936619743392459"

    yielded_count = 0
    seen_codes: Set[str] = set()

    for node in nodes:
        code = node.get("code") or node.get("shortcode")
        if code and code not in seen_codes:
            seen_codes.add(code)
            yield node
            yielded_count += 1
            if limit > 0 and yielded_count >= limit:
                return

    has_next_page = bool(page_info.get("has_next_page", False))
    end_cursor = page_info.get("end_cursor")

    page_num = 1
    while has_next_page and end_cursor:
        if limit > 0 and yielded_count >= limit:
            break

        page_num += 1
        if page_delay > 0:
            logger.info(f"Waiting {page_delay:.1f}s before fetching page {page_num} to avoid rate-limiting...")
            time.sleep(page_delay)

        logger.info(f"Fetching page {page_num} of posts via GraphQL (cursor: {end_cursor[:20]}...)...")
        next_nodes, next_page_info = fetch_profile_posts_page_graphql(
            session=session,
            username=username,
            user_id=user_id,
            end_cursor=end_cursor,
            csrf_token=csrf_token,
            lsd_token=lsd_token,
            app_id=app_id,
            user_pk=user_pk,
        )

        if not next_nodes:
            if not session.cookies.get("sessionid"):
                logger.info("Zakonczono pobieranie dostepnej siatki profilu (maksymalny limit 12 postow dla sesji bez logowania).")
            else:
                logger.info(f"Brak kolejnych postow na stronie {page_num} (koniec osi czasu).")
            break

        logger.info(f"Page {page_num}: retrieved {len(next_nodes)} posts.")
        for node in next_nodes:
            code = node.get("code") or node.get("shortcode")
            if code and code not in seen_codes:
                seen_codes.add(code)
                yield node
                yielded_count += 1
                if limit > 0 and yielded_count >= limit:
                    return

        has_next_page = bool(next_page_info.get("has_next_page", False))
        end_cursor = next_page_info.get("end_cursor")
        if not has_next_page or not end_cursor:
            logger.info("Reached the end of posts on the profile (has_next_page == False).")
            break


def fetch_profile_posts(
    username: str,
    limit: int = 12,
    page_delay: float = 1.5,
    session: Optional[requests.Session] = None,
    cookies_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch list of posts from a public Instagram profile (up to limit)."""
    posts = []
    for node in iterate_profile_posts(
        username=username,
        limit=limit,
        page_delay=page_delay,
        session=session,
        cookies_path=cookies_path,
    ):
        posts.append(node)
        if limit > 0 and len(posts) >= limit:
            break
    return posts


def fetch_post_details(shortcode: str, session: Optional[requests.Session] = None) -> Optional[Dict[str, Any]]:
    """
    Fetch full post metadata from dedicated view https://www.instagram.com/p/<shortcode>/
    to retrieve highest resolution media formats (image_versions2, display_resources, carousel_media).
    """
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    headers = {
        "Accept-Language": "en-US,en;q=0.9",
    }
    logger.info(f"Fetching detailed metadata from post view: {post_url} ...")
    client = session if session is not None else requests
    try:
        response = client.get(post_url, impersonate="chrome", headers=headers, timeout=25)
    except Exception as e:
        logger.warning(f"Connection error while fetching post view for {shortcode}: {e}")
        return None

    if response.status_code != 200:
        logger.warning(f"Post view for {shortcode} returned HTTP {response.status_code}.")
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
    Select image URL with highest available resolution from metadata.
    Priority:
    1. candidates from image_versions2 (highest width x height or uncompressed original)
    2. display_resources (sorted by config_width * config_height)
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
    """Select video URL with highest resolution from video_versions."""
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
    """Download file from URL and save to the specified path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, impersonate="chrome", timeout=40)
        if r.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(r.content)
            return True
        logger.error(f"Failed to download file {output_path.name} (HTTP {r.status_code})")
        return False
    except Exception as e:
        logger.error(f"Error saving file {output_path.name}: {e}")
        return False


def download_image_and_log_dimensions(url: str, output_path: Path) -> bool:
    """Download image from URL and log its pixel dimensions using Pillow."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, impersonate="chrome", timeout=30)
        if r.status_code != 200:
            logger.error(f"Failed to download image from {url[:80]}... (HTTP {r.status_code})")
            return False

        with open(output_path, "wb") as f:
            f.write(r.content)

        file_size_kb = len(r.content) / 1024

        try:
            with Image.open(output_path) as img:
                width, height = img.size
            logger.info(
                f"Saved full-resolution image 'images/{output_path.name}': "
                f"resolution: {width}x{height} px, size: {file_size_kb:.1f} KB"
            )
        except Exception as e:
            logger.info(
                f"Saved image 'images/{output_path.name}' ({file_size_kb:.1f} KB), "
                f"could not read dimensions: {e}"
            )

        return True
    except Exception as e:
        logger.error(f"Error while saving image {output_path.name}: {e}")
        return False


def download_post_media(
    node: Dict[str, Any],
    profile_name: str,
    images_dir: Path,
    videos_dir: Path,
    archive_path: Path,
    session: Optional[requests.Session] = None,
    cookies_path: Optional[str] = None,
) -> bool:
    """
    Download media for given post node in highest available quality:
      - Images are saved to 'images/' subdirectory.
      - Videos are saved to 'videos/' subdirectory.
    For carousels (multi-item galleries):
      - Items are saved cleanly as {code}_1.ext, {code}_2.ext ... (no duplicates).
    For single posts:
      - File is saved as {code}.ext in the corresponding directory.
    """
    code = node.get("code") or node.get("shortcode")
    if not code:
        return False
    node["code"] = code

    # Normalize media type and carousel items from legacy or modern schema
    if "carousel_media" not in node and "edge_sidecar_to_children" in node:
        edges = node.get("edge_sidecar_to_children", {}).get("edges", [])
        node["carousel_media"] = [e.get("node") for e in edges if e.get("node")]

    media_type = node.get("media_type")
    if media_type is None:
        if node.get("is_video") or node.get("video_versions"):
            media_type = 2
        elif node.get("carousel_media"):
            media_type = 8
        else:
            media_type = 1

    post_url = f"https://www.instagram.com/p/{code}/"

    images_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)
    downloaded = False

    # Fetch post metadata for maximum resolution
    post_details = fetch_post_details(code, session=session) or node
    carousel_media = post_details.get("carousel_media") or []

    # 1. Handle carousel (gallery)
    if len(carousel_media) > 1:
        logger.info(
            f"Post {code} is a carousel ({len(carousel_media)} items). "
            f"Downloading slides in full resolution..."
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
                        logger.info(f"Saved video 'videos/{out_file.name}' ({file_size_kb:.1f} KB)")
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

    # 2. Handle single video
    is_single_video = not downloaded and (media_type == 2 or bool(post_details.get("video_versions")))
    if is_single_video:
        ffmpeg_path = get_ffmpeg_path()
        logger.info(f"Downloading video at maximum quality via yt-dlp ({post_url})...")

        ydl_opts: Dict[str, Any] = {
            "outtmpl": str(videos_dir / f"{code}.%(ext)s"),
            "download_archive": str(archive_path),
            "format_sort": ["res", "fps", "size", "br"],
            "quiet": False,
            "no_warnings": True,
        }

        if cookies_path and Path(cookies_path).is_file():
            ydl_opts["cookiefile"] = str(cookies_path)

        if ffmpeg_path:
            ydl_opts["ffmpeg_location"] = ffmpeg_path
            ydl_opts["format"] = "bestvideo+bestaudio/best"
        else:
            logger.warning("No ffmpeg detected on system - falling back to pre-merged video format.")
            ydl_opts["format"] = "b[vcodec!=none][acodec!=none]/best[ext=mp4]/best"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ret = ydl.download([post_url])
                if ret == 0:
                    downloaded = True
                    logger.info(f"Successfully downloaded video 'videos/{code}.mp4'.")
        except Exception as e:
            logger.warning(f"yt-dlp encountered an issue with {code}: {e}")
            try:
                fallback_opts = {
                    "outtmpl": str(videos_dir / f"{code}.%(ext)s"),
                    "download_archive": str(archive_path),
                    "format": "b[vcodec!=none][acodec!=none]/best[ext=mp4]/best",
                    "quiet": True,
                    "no_warnings": True,
                }
                if cookies_path and Path(cookies_path).is_file():
                    fallback_opts["cookiefile"] = str(cookies_path)
                with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                    ret = ydl.download([post_url])
                    if ret == 0:
                        downloaded = True
                        logger.info(f"Successfully downloaded video {code} using fallback format.")
            except Exception as e2:
                logger.error(f"Failed to download video {code} in fallback mode: {e2}")

    # 3. Handle single image (or 1-item carousel)
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
    page_delay: float = 1.5,
    cookies_path: Optional[str] = None,
) -> int:
    """
    Monitor profile, check history, and download up to N new media files into images/ and videos/ subdirectories.
    Paginates across multiple pages until limit is reached, a previously downloaded post is encountered,
    or the profile has no more posts.
    """
    username = extract_username(profile_input)
    target_dir = download_dir / username
    images_dir = target_dir / "images"
    videos_dir = target_dir / "videos"
    archive_path = target_dir / "archive.txt"

    images_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)

    downloaded_ids = load_downloaded_posts(db_path)
    logger.info(f"Loaded {len(downloaded_ids)} previously downloaded posts from {db_path}")

    session = requests.Session()
    effective_cookiefile = cookies_path if (cookies_path and Path(cookies_path).is_file()) else None
    if cookies_path:
        load_cookies_into_session(session, cookies_path)
        if not effective_cookiefile:
            try:
                temp_cf = target_dir / "cookies.txt"
                with open(temp_cf, "w", encoding="utf-8") as f:
                    f.write("# Netscape HTTP Cookie File\n")
                    for name, value in session.cookies.items():
                        f.write(f".instagram.com\tTRUE\t/\tTRUE\t2147483647\t{name}\t{value}\n")
                effective_cookiefile = str(temp_cf)
            except Exception as e:
                logger.debug(f"Could not generate cookiefile for yt-dlp: {e}")

    posts_checked = 0
    posts_downloaded = 0

    for node in iterate_profile_posts(
        username=username,
        limit=0,
        page_delay=page_delay,
        session=session,
        cookies_path=cookies_path,
    ):
        if limit > 0 and posts_downloaded >= limit:
            logger.info(f"Reached download limit of new posts ({limit}).")
            break

        posts_checked += 1
        code = node.get("code") or node.get("shortcode")
        if not code:
            continue

        # Stop if post was already downloaded (since checking from newest to oldest)
        if code in downloaded_ids:
            logger.info(
                f"[{posts_checked}] Post {code} was already downloaded. "
                f"Reached previously processed posts - stopping search."
            )
            break

        logger.info(f"[{posts_checked}] Processing new post: {code} ...")
        success = download_post_media(
            node=node,
            profile_name=username,
            images_dir=images_dir,
            videos_dir=videos_dir,
            archive_path=archive_path,
            session=session,
            cookies_path=effective_cookiefile,
        )
        if success:
            downloaded_ids.add(code)
            save_downloaded_posts(db_path, downloaded_ids)
            posts_downloaded += 1
            logger.info(f"Successfully saved post {code}.")
        else:
            logger.warning(f"Failed to save media for post {code}.")

        if limit > 0 and posts_downloaded >= limit:
            logger.info(f"Reached download limit of new posts ({limit}).")
            break

    logger.info(
        f"Completed. Posts checked: {posts_checked}, newly downloaded: {posts_downloaded}."
    )
    return posts_downloaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor a public Instagram profile and download media into images/ and videos/ subdirectories."
    )
    parser.add_argument(
        "--profile",
        "-p",
        required=True,
        type=str,
        help="Instagram profile username or full URL (e.g. 'nasa' or 'https://www.instagram.com/nasa/').",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=1,
        help="Number of latest posts to download (default: 1).",
    )
    parser.add_argument(
        "--download-dir",
        type=str,
        default="downloads",
        help="Target directory for downloaded media (default: 'downloads').",
    )
    parser.add_argument(
        "--db-file",
        type=str,
        default="downloaded_posts.json",
        help="Path to JSON file tracking downloaded posts (default: 'downloaded_posts.json').",
    )
    parser.add_argument(
        "--page-delay",
        type=float,
        default=1.5,
        help="Delay in seconds between fetching pagination pages (default: 1.5).",
    )
    parser.add_argument(
        "--cookies",
        type=str,
        default=None,
        help="Path to cookies file (Netscape format) or cookies string for authentication.",
    )

    args = parser.parse_args()

    if args.limit < 1:
        parser.error("The --limit value must be greater than zero.")

    return args


def main():
    args = parse_args()
    watch_profile(
        profile_input=args.profile,
        limit=args.limit,
        download_dir=Path(args.download_dir),
        db_path=Path(args.db_file),
        page_delay=args.page_delay,
        cookies_path=args.cookies,
    )


if __name__ == "__main__":
    main()
