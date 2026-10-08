import json
from pathlib import Path
import pytest

from instagram_watcher import (
    extract_username,
    load_downloaded_posts,
    save_downloaded_posts,
    select_best_image_url,
    select_best_video_url,
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

    # Plik jeszcze nie istnieje
    assert load_downloaded_posts(db_file) == set()

    # Zapis danych
    initial_ids = {"post_1", "post_2", "post_3"}
    save_downloaded_posts(db_file, initial_ids)

    # Odczyt danych
    loaded_ids = load_downloaded_posts(db_file)
    assert loaded_ids == initial_ids

    # Sprawdzenie poprawności formatu JSON
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
