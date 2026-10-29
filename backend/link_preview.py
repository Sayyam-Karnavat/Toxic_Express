"""Link preview cards (title/description/site) fetched through the SSRF-safe client.

Images from third-party pages are not stored or hotlinked, to protect readers' privacy.
"""

import logging
import re
import uuid
from html.parser import HTMLParser
from urllib.parse import urlsplit

from sqlalchemy import select

from database import SessionLocal
from models import ModerationState, Post
from safe_fetch import BlockedURLError, safe_get
from utils import clean_text

logger = logging.getLogger(__name__)

_URL = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)
MAX_HTML_BYTES = 512 * 1024


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if (
                key
                in (
                    "og:title",
                    "og:description",
                    "og:site_name",
                    "description",
                    "twitter:title",
                    "twitter:description",
                )
                and key not in self.meta
            ):
                self.meta[key] = values.get("content", "")
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and len(self.title) < 300:
            self.title += data


def parse_preview(url: str, html: str) -> dict[str, str] | None:
    parser = _MetaParser()
    try:
        parser.feed(html)
    except Exception:  # malformed HTML: best effort only
        logger.debug("preview parse failed for %s", url, exc_info=True)
    meta = parser.meta
    title = meta.get("og:title") or meta.get("twitter:title") or parser.title
    description = (
        meta.get("og:description")
        or meta.get("twitter:description")
        or meta.get("description")
        or ""
    )
    title = clean_text(title, multiline=False)[:200]
    if not title:
        return None
    domain = (urlsplit(url).hostname or "").removeprefix("www.")
    return {
        "url": url,
        "domain": domain,
        "title": title,
        "description": clean_text(description, multiline=False)[:300],
        "site_name": clean_text(meta.get("og:site_name", ""), multiline=False)[:80],
    }


async def fetch_for_post(post_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        post = await db.scalar(select(Post).where(Post.id == post_id))
        if post is None or post.moderation_state != ModerationState.published or post.link_preview:
            return
        match = _URL.search(post.body)
        if not match:
            return
        url = match.group().rstrip(".,!?;:")
    try:
        fetched = await safe_get(url, max_bytes=MAX_HTML_BYTES)
    except (BlockedURLError, OSError, TimeoutError, Exception) as exc:
        logger.info("link preview skipped for %s: %r", url, exc)
        return
    if fetched.status != 200 or "html" not in fetched.content_type:
        return
    preview = parse_preview(fetched.url, fetched.body.decode("utf-8", errors="replace"))
    if preview is None:
        return
    async with SessionLocal() as db:
        post = await db.get(Post, post_id)
        if post is not None:
            post.link_preview = preview
            await db.commit()
