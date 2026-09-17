import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("BOT_TOKEN", "test-token")

from bot import extract_url, is_youtube_url, safe_filename  # noqa: E402


def test_youtube_url_validation():
    assert is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert is_youtube_url("https://youtu.be/abc")
    assert not is_youtube_url("https://example.com/watch?v=abc")


def test_extract_url():
    assert extract_url("download this https://youtu.be/abc!!!") == "https://youtu.be/abc"
    assert extract_url("nothing here") is None


def test_safe_filename():
    assert "/" not in safe_filename('hello/world: test?')
