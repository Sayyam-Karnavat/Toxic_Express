import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from cache import hit_rate_limit
from errors import AppError
from link_preview import parse_preview
from moderation import Verdict, apply_policy, check_local_rules
from safe_fetch import BlockedURLError, is_public_ip, safe_get, validate_url
from utils import clean_text, decode_cursor, encode_cursor, uuid7


@pytest.mark.parametrize(
    ("ip", "public"),
    [
        ("8.8.8.8", True),
        ("1.1.1.1", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("192.168.0.10", False),
        ("172.16.5.4", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("0.0.0.0", False),
        ("::1", False),
        ("fd00::1", False),
        ("::ffff:127.0.0.1", False),
        ("2606:4700:4700::1111", True),
        ("224.0.0.1", False),
    ],
)
def test_is_public_ip(ip, public):
    assert is_public_ip(ip) is public


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://x",
        "http://user:pw@example.com",
        "http://example.com:6379",
        "http://127.0.0.1/",
        "http://[::1]/",
        "ftp://example.com",
    ],
)
def test_validate_url_rejects(url):
    with pytest.raises(BlockedURLError):
        validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:80/",
        "http://localhost/",
        "http://127.0.0.1.nip.io/",
        "http://metadata.google.internal/",
    ],
)
async def test_safe_get_blocks_internal_hosts_after_dns(url):
    with pytest.raises((BlockedURLError, OSError)):
        await safe_get(url, max_bytes=1000, timeout=2)


def test_parse_preview_and_escaping():
    html = """<html><head><title>Fallback</title>
    <meta property="og:title" content="Airline lost my bag &amp; laughed">
    <meta name="description" content="A <b>story</b>">
    <meta property="og:site_name" content="News"></head></html>"""
    preview = parse_preview("https://www.example.com/a", html)
    assert preview == {
        "url": "https://www.example.com/a",
        "domain": "example.com",
        "title": "Airline lost my bag & laughed",
        "description": "A story",
        "site_name": "News",
    }
    assert parse_preview("https://x.com", "<html></html>") is None


def test_cursor_roundtrip_and_tamper():
    now = datetime.now(UTC)
    rid = uuid.uuid4()
    assert decode_cursor(encode_cursor(now, rid)) == (now, rid)
    for bad in ("x", "eyJ0IjoiMjAyMCJ9", "e30"):
        with pytest.raises(AppError):
            decode_cursor(bad)


def test_uuid7_is_time_ordered_and_valid():
    ids = [uuid7() for _ in range(200)]
    assert all(i.version == 7 and i.variant == uuid.RFC_4122 for i in ids)
    stamps = [i.int >> 80 for i in ids]
    assert stamps == sorted(stamps)


def test_clean_text():
    assert clean_text("  a\u0000b  ", multiline=False) == "ab"
    assert clean_text("x <img src=x onerror=alert(1)> y", multiline=False) == "x y"
    assert clean_text("1 < 2 and 3 > 2", multiline=False) == "1 < 2 and 3 > 2"
    assert clean_text("a\r\n\r\n\r\n\r\nb") == "a\n\nb"


def test_policy_merge_and_local_rules():
    merged = Verdict("review", reasons=["a"]).merge(Verdict("reject", reasons=["b"], crisis=True))
    assert merged.action == "reject" and merged.crisis and merged.reasons == ["a", "b"]
    assert apply_policy({"violence": 0.6}).action == "allow"
    assert (
        check_local_rules("see http://a.com http://b.com http://c.com http://d.com").action
        == "review"
    )


async def test_rate_limiter_sliding_window():
    key = f"unit:{uuid.uuid4()}"
    results = [await hit_rate_limit(key, 3, 60) for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert results[-1].retry_after >= 1 and results[0].remaining == 2


async def test_rate_limiter_is_atomic_under_concurrency():
    key = f"unit:{uuid.uuid4()}"
    results = await asyncio.gather(*(hit_rate_limit(key, 10, 60) for _ in range(50)))
    assert sum(r.allowed for r in results) == 10
