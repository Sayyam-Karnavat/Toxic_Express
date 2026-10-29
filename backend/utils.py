"""Small shared helpers: UUIDv7 ids, time, cursors, text normalisation."""

import base64
import json
import os
import re
import time
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any

import nh3
from sqlalchemy import ColumnElement, literal, tuple_

from errors import bad_request


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: 48-bit unix ms timestamp + random bits. Time-ordered, index friendly."""
    ts_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    rand_a = rand >> 68  # 12 bits
    rand_b = rand & ((1 << 62) - 1)  # 62 bits
    value = (ts_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b
    return uuid.UUID(int=value)


def utcnow() -> datetime:
    return datetime.now(UTC)


# --- Cursor pagination -------------------------------------------------------------------------


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "i": str(row_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        created_at = datetime.fromisoformat(data["t"])
        if created_at.tzinfo is None:
            raise ValueError("naive timestamp")
        return created_at, uuid.UUID(data["i"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise bad_request("invalid_cursor", "Invalid pagination cursor") from exc


def keyset_before(
    time_col: Any, id_col: Any, position: tuple[datetime, uuid.UUID]
) -> ColumnElement[bool]:
    """(time, id) < cursor, for DESC ordering. Uses a row-value comparison the index can serve."""
    return tuple_(time_col, id_col) < tuple_(literal(position[0]), literal(position[1]))


def keyset_after(
    time_col: Any, id_col: Any, position: tuple[datetime, uuid.UUID]
) -> ColumnElement[bool]:
    """(time, id) > cursor, for ASC ordering."""
    return tuple_(time_col, id_col) > tuple_(literal(position[0]), literal(position[1]))


def encode_offset_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode().rstrip("=")


def decode_offset_cursor(cursor: str | None, max_offset: int) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        prefix, value = base64.urlsafe_b64decode(padded.encode()).decode().split(":", 1)
        offset = int(value)
        if prefix != "o" or not 0 <= offset <= max_offset:
            raise ValueError
        return offset
    except (ValueError, UnicodeDecodeError) as exc:
        raise bad_request("invalid_cursor", "Invalid pagination cursor") from exc


# --- Text --------------------------------------------------------------------------------------

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(value: str, *, multiline: bool = True) -> str:
    """Normalise user text: NFC, strip HTML tags, control / bidi-override chars, excess blank lines.

    Content is stored as Markdown-lite plain text; the frontend renders it without raw HTML.
    """
    text = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    text = nh3.clean(text, tags=set(), attributes={}, strip_comments=True)
    # nh3 escapes &, < and >; we store plain text and the client escapes on render.
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    text = _CONTROL_CHARS.sub("", text)
    text = _MANY_BLANK_LINES.sub("\n\n", text) if multiline else " ".join(text.split())
    return text.strip()


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
