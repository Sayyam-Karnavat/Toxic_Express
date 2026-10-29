import io
from datetime import timedelta

import httpx
import pytest
from arq import Retry
from PIL import Image
from sqlalchemy import select, update

import link_preview
import mailer
import media_service
import worker
from database import SessionLocal
from models import Media, MediaKind, MediaPurpose, MediaState, Post, User, UserStatus
from safe_fetch import FetchResult
from tests.conftest import create_rant, make_user
from utils import utcnow, uuid7


async def test_purge_anonymises_due_accounts(client: httpx.AsyncClient):
    leaver, lh = await make_user("leaver")
    _, fh = await make_user("friend_f")
    await client.post("/api/v1/users/leaver/follow", headers=fh)
    await client.post("/api/v1/users/friend_f/follow", headers=lh)
    post = await create_rant(client, lh)
    async with SessionLocal() as db:
        await db.execute(
            update(User)
            .where(User.id == leaver.id)
            .values(
                status=UserStatus.deleted, deletion_scheduled_at=utcnow() - timedelta(minutes=1)
            )
        )
        await db.commit()
    await worker.cron_purge_accounts({})
    async with SessionLocal() as db:
        user = await db.get(User, leaver.id)
        assert user.handle.startswith("deleted_") and user.email.endswith("@invalid.toxic-express")
        assert user.display_name == "Deleted user" and user.password_hash is None
        assert (await db.get(Post, post["id"])).deleted_at is not None
    friend = (await client.get("/api/v1/users/friend_f")).json()
    assert friend["follower_count"] == 0 and friend["following_count"] == 0


async def test_cleanup_stale_uploads():
    owner, _ = await make_user("stale")
    async with SessionLocal() as db:
        db.add(
            Media(
                id=uuid7(),
                owner_id=owner.id,
                purpose=MediaPurpose.post,
                kind=MediaKind.image,
                mime="image/png",
                size_bytes=10,
                state=MediaState.uploading,
                created_at=utcnow() - timedelta(days=2),
            )
        )
        fresh = Media(
            id=uuid7(),
            owner_id=owner.id,
            purpose=MediaPurpose.post,
            kind=MediaKind.image,
            mime="image/png",
            size_bytes=10,
            state=MediaState.uploading,
        )
        db.add(fresh)
        await db.commit()
    assert await media_service.cleanup_stale_uploads() == 1
    async with SessionLocal() as db:
        states = sorted(m.state.value for m in (await db.scalars(select(Media))).all())
    assert states == ["deleted", "uploading"]


async def test_link_preview_job(client: httpx.AsyncClient, monkeypatch):
    async def fake_get(url, **kwargs):
        assert url == "https://news.example.com/story"
        html = b'<meta property="og:title" content="Airport chaos"><title>x</title>'
        return FetchResult(url=url, status=200, content_type="text/html", body=html)

    monkeypatch.setattr(link_preview, "safe_get", fake_get)
    _, h = await make_user("linker_l")
    post = await create_rant(client, h, body="Look at this: https://news.example.com/story.")
    detail = (await client.get(f"/api/v1/posts/{post['id']}")).json()
    assert detail["link_preview"]["title"] == "Airport chaos"
    assert detail["link_preview"]["domain"] == "news.example.com"


async def test_google_avatar_import_only_from_google(monkeypatch):
    user, _ = await make_user("googler")
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), (10, 200, 30)).save(buf, "PNG")
    calls = []

    async def fake_get(url, **kwargs):
        calls.append(url)
        return FetchResult(url=url, status=200, content_type="image/png", body=buf.getvalue())

    monkeypatch.setattr(media_service, "safe_get", fake_get)
    await media_service.import_remote_avatar(str(user.id), "https://evil.example.com/a.png")
    assert calls == []
    await media_service.import_remote_avatar(str(user.id), "https://lh3.googleusercontent.com/a/x")
    async with SessionLocal() as db:
        refreshed = await db.get(User, user.id)
    assert set(refreshed.avatar) == {"400", "96"}


async def test_email_job_retries_then_gives_up(monkeypatch):
    async def boom(email):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(mailer, "deliver", boom)
    with pytest.raises(Retry):
        await worker.send_email({"job_try": 1}, "verification", "a@b.c", "A", "tok")
    await worker.send_email({"job_try": worker.MAX_TRIES}, "verification", "a@b.c", "A", "tok")


async def test_trending_cron(client: httpx.AsyncClient):
    _, h = await make_user("trendy")
    await create_rant(client, h)
    await worker.cron_trending({})
    assert len((await client.get("/api/v1/feed", params={"sort": "trending"})).json()["items"]) == 1
