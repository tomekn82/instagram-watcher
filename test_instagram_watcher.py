import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from curl_cffi import requests

from instagram_watcher import (
    extract_username,
    fetch_profile_posts,
    find_edges_and_page_info,
    iterate_profile_posts,
    load_cookies_into_session,
    load_downloaded_posts,
    save_downloaded_posts,
    select_best_image_url,
    select_best_video_url,
    watch_profile,
)


def test_extract_username():
    assert extract_username("nasa") == "nasa"
    assert extract_username("@nasa") == "nasa"
    assert extract_username("https://www.instagram.com/nasa/") == "nasa"
    assert extract_username("https://www.instagram.com/nasa") == "nasa"
    assert extract_username("https://www.instagram.com/nasa?igsh=123") == "nasa"
    assert extract_username("https://www.instagram.com/nasa/#fragment") == "nasa"


def test_load_and_save_downloaded_posts(tmp_path: Path):
    db_file = tmp_path / "downloaded_posts.json"

    # File does not exist yet
    assert load_downloaded_posts(db_file) == set()

    # Save data
    initial_ids = {"post_1", "post_2", "post_3"}
    save_downloaded_posts(db_file, initial_ids)

    # Read data
    loaded_ids = load_downloaded_posts(db_file)
    assert loaded_ids == initial_ids

    # Validate JSON structure
    with open(db_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert isinstance(data, list)
        assert sorted(data) == sorted(list(initial_ids))


def test_load_downloaded_posts_dict_compatibility(tmp_path: Path):
    db_file = tmp_path / "legacy_posts.json"
    legacy_data = {
        "profile1": ["p1", "p2"],
        "profile2": ["p3"],
    }
    with open(db_file, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)

    loaded = load_downloaded_posts(db_file)
    assert loaded == {"p1", "p2", "p3"}


def test_select_best_image_url_candidates():
    media_dict = {
        "original_width": 1440,
        "original_height": 1800,
        "image_versions2": {
            "candidates": [
                {"url": "https://cdn.example.com/photo.jpg?stp=dst-jpg_e35_p640x640"},
                {"url": "https://cdn.example.com/photo.jpg?stp=dst-jpg_e35_tt6"},  # Original
                {"url": "https://cdn.example.com/photo.jpg?stp=dst-jpg_e35_p1080x1080"},
            ]
        },
    }
    best_url = select_best_image_url(media_dict)
    assert "dst-jpg_e35_tt6" in best_url


def test_select_best_image_url_display_resources():
    media_dict = {
        "display_resources": [
            {"src": "https://cdn.example.com/640.jpg", "config_width": 640, "config_height": 640},
            {"src": "https://cdn.example.com/1080.jpg", "config_width": 1080, "config_height": 1080},
        ]
    }
    best_url = select_best_image_url(media_dict)
    assert best_url == "https://cdn.example.com/1080.jpg"


def test_select_best_video_url():
    media_dict = {
        "video_versions": [
            {"url": "https://cdn.example.com/low.mp4", "width": 480, "height": 852},
            {"url": "https://cdn.example.com/high.mp4", "width": 1080, "height": 1920},
            {"url": "https://cdn.example.com/mid.mp4", "width": 720, "height": 1280},
        ]
    }
    best_url = select_best_video_url(media_dict)
    assert best_url == "https://cdn.example.com/high.mp4"


def test_find_edges_and_page_info_graphql():
    data = {
        "data": {
            "user": {
                "polaris_ordered_timeline_connection": {
                    "edges": [
                        {"node": {"shortcode": "code1", "media_type": 1}},
                        {"node": {"code": "code2", "media_type": 2}},
                    ],
                    "page_info": {
                        "has_next_page": True,
                        "end_cursor": "cursor_123",
                    },
                }
            }
        }
    }
    nodes, page_info = find_edges_and_page_info(data)
    assert len(nodes) == 2
    assert nodes[0]["code"] == "code1"
    assert nodes[1]["code"] == "code2"
    assert page_info.get("has_next_page") is True
    assert page_info.get("end_cursor") == "cursor_123"


def test_find_edges_and_page_info_rest():
    data = {
        "items": [
            {"pk": "111", "code": "rest_1", "media_type": 1},
            {"pk": "222", "code": "rest_2", "media_type": 2},
        ],
        "more_available": True,
        "next_max_id": "max_id_456",
    }
    nodes, page_info = find_edges_and_page_info(data)
    assert len(nodes) == 2
    assert nodes[0]["code"] == "rest_1"
    assert page_info.get("has_next_page") is True
    assert page_info.get("end_cursor") == "max_id_456"


def test_load_cookies_into_session_netscape(tmp_path: Path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\tmy_test_session\n"
        ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tds_user_id\t12345678\n",
        encoding="utf-8",
    )
    session = requests.Session()
    load_cookies_into_session(session, str(cookie_file))
    assert session.cookies.get("sessionid") == "my_test_session"
    assert session.cookies.get("ds_user_id") == "12345678"


def test_load_cookies_into_session_raw(tmp_path: Path):
    cookie_file = tmp_path / "raw_cookies.txt"
    cookie_file.write_text("sessionid=abc123xyz; csrftoken=csrftest99;", encoding="utf-8")
    session = requests.Session()
    load_cookies_into_session(session, str(cookie_file))
    assert session.cookies.get("sessionid") == "abc123xyz"
    assert session.cookies.get("csrftoken") == "csrftest99"


def test_load_cookies_into_session_token():
    session = requests.Session()
    token = "6829141092%3Aabcde12345%3A29"
    load_cookies_into_session(session, token)
    assert session.cookies.get("sessionid") == token


def test_iterate_profile_posts_pagination(monkeypatch):
    mock_html = (
        '<html><body>'
        '<script type="application/json">'
        '{"data":{"user":{"polaris_ordered_timeline_connection":{"edges":['
        + ",".join([f'{{"node":{{"code":"post_{i}","media_type":1}}}}' for i in range(1, 13)])
        + '],"page_info":{"has_next_page":true,"end_cursor":"cursor_page1"}}}}}'
        '</script>'
        '</body></html>'
    )

    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_html
    mock_session.get.return_value = mock_resp
    mock_session.cookies = {}

    page2_nodes = [{"code": f"post_{i}", "media_type": 1} for i in range(13, 21)]
    page2_page_info = {"has_next_page": False, "end_cursor": None}

    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    monkeypatch.setattr(
        "instagram_watcher.fetch_profile_posts_page_graphql",
        lambda *args, **kwargs: (
            page2_nodes,
            page2_page_info,
        ),
    )

    posts = list(
        iterate_profile_posts(
            username="testuser",
            limit=25,
            page_delay=1.5,
            session=mock_session,
        )
    )

    assert len(posts) == 20
    assert posts[0]["code"] == "post_1"
    assert posts[11]["code"] == "post_12"
    assert posts[12]["code"] == "post_13"
    assert posts[19]["code"] == "post_20"
    assert sleep_calls == [1.5]


def test_iterate_profile_posts_stops_at_limit(monkeypatch):
    mock_html = (
        '<html><body>'
        '<script type="application/json">'
        '{"data":{"user":{"polaris_ordered_timeline_connection":{"edges":['
        + ",".join([f'{{"node":{{"code":"post_{i}","media_type":1}}}}' for i in range(1, 13)])
        + '],"page_info":{"has_next_page":true,"end_cursor":"cursor_page1"}}}}}'
        '</script>'
        '</body></html>'
    )
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_html
    mock_session.get.return_value = mock_resp
    mock_session.cookies = {}

    graphql_called = []
    monkeypatch.setattr(
        "instagram_watcher.fetch_profile_posts_page_graphql",
        lambda *args, **kwargs: graphql_called.append(True) or ([], {}),
    )

    posts = list(iterate_profile_posts(username="testuser", limit=5, session=mock_session))
    assert len(posts) == 5
    assert [p["code"] for p in posts] == [f"post_{i}" for i in range(1, 6)]
    assert len(graphql_called) == 0


def test_watch_profile_termination_on_limit(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "downloaded_posts.json"
    download_dir = tmp_path / "downloads"

    mock_nodes = [{"code": f"post_{i}"} for i in range(1, 11)]

    monkeypatch.setattr(
        "instagram_watcher.iterate_profile_posts",
        lambda *args, **kwargs: iter(mock_nodes),
    )
    monkeypatch.setattr(
        "instagram_watcher.download_post_media",
        lambda **kwargs: True,
    )

    downloaded = watch_profile(
        profile_input="nasa",
        limit=3,
        download_dir=download_dir,
        db_path=db_file,
    )

    assert downloaded == 3
    saved_ids = load_downloaded_posts(db_file)
    assert saved_ids == {"post_1", "post_2", "post_3"}


def test_watch_profile_termination_on_downloaded_posts(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "downloaded_posts.json"
    download_dir = tmp_path / "downloads"

    # Pre-populate database with post_3
    save_downloaded_posts(db_file, {"post_3"})

    mock_nodes = [{"code": f"post_{i}"} for i in range(1, 6)]
    downloaded_calls = []

    monkeypatch.setattr(
        "instagram_watcher.iterate_profile_posts",
        lambda *args, **kwargs: iter(mock_nodes),
    )
    monkeypatch.setattr(
        "instagram_watcher.download_post_media",
        lambda **kwargs: downloaded_calls.append(kwargs["node"]["code"]) or True,
    )

    downloaded = watch_profile(
        profile_input="nasa",
        limit=10,
        download_dir=download_dir,
        db_path=db_file,
    )

    # Must only download post_1 and post_2; stops on post_3
    assert downloaded == 2
    assert downloaded_calls == ["post_1", "post_2"]
    saved_ids = load_downloaded_posts(db_file)
    assert saved_ids == {"post_1", "post_2", "post_3"}


def test_watch_profile_termination_on_exhausted_posts(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "downloaded_posts.json"
    download_dir = tmp_path / "downloads"

    mock_nodes = [{"code": "post_1"}, {"code": "post_2"}]

    monkeypatch.setattr(
        "instagram_watcher.iterate_profile_posts",
        lambda *args, **kwargs: iter(mock_nodes),
    )
    monkeypatch.setattr(
        "instagram_watcher.download_post_media",
        lambda **kwargs: True,
    )

    downloaded = watch_profile(
        profile_input="nasa",
        limit=50,
        download_dir=download_dir,
        db_path=db_file,
    )

    assert downloaded == 2
    saved_ids = load_downloaded_posts(db_file)
    assert saved_ids == {"post_1", "post_2"}


def test_fetch_profile_posts_wrapper(monkeypatch):
    mock_nodes = [{"code": f"post_{i}"} for i in range(1, 10)]
    monkeypatch.setattr(
        "instagram_watcher.iterate_profile_posts",
        lambda username, limit, **kwargs: iter(mock_nodes[:limit]),
    )
    posts = fetch_profile_posts("nasa", limit=4)
    assert len(posts) == 4
    assert [p["code"] for p in posts] == ["post_1", "post_2", "post_3", "post_4"]

