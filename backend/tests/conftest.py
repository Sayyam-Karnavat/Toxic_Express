"""Test fixtures: isolated Postgres database, Redis DB and S3 buckets; jobs run inline."""

import os

os.environ.update(
    {
        "ENV": "test",
        "DATABASE_URL": "postgresql+asyncpg://toxic:toxic@localhost:5433/toxic_express_test",
        "REDIS_URL": "redis://localhost:6380/1",
        "TASKS_EAGER": "true",
        "MEDIA_MIN_ACCOUNT_AGE_HOURS": "0",
        "S3_BUCKET_RAW": "te-test-raw",
        "S3_BUCKET_PUBLIC": "te-test-public",
        "MEDIA_PUBLIC_BASE_URL": "http://localhost:8333/te-test-public",
        "OPENAI_API_KEY": "",
        "RESEND_API_KEY": "",
        "GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "test-google-secret",
        "GOOGLE_REDIRECT_URI": "http://test/api/v1/auth/google/callback",
        "FRONTEND_URL": "http://frontend.test",
        "LOG_LEVEL": "WARNING",
    }
)

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

import mailer
from cache import get_redis, init_redis
from database import SessionLocal, engine
from main import app
from models import AuthSession, Base, Role, User, UserSettings
from security import create_access_token, hash_password, new_refresh_token
from storage import ensure_buckets
from utils import utcnow, uuid7

TEST_PASSWORD = "Correct-Horse-42!"
_password_hash: str | None = None


async def _create_database() -> None:
    conn = await asyncpg.connect("postgresql://toxic:toxic@localhost:5433/postgres")
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname='toxic_express_test'"):
            await conn.execute("CREATE DATABASE toxic_express_test")
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
async def _setup_infra() -> AsyncIterator[None]:
    await _create_database()
    cfg = Config("alembic.ini")
    await engine.dispose()
    import anyio

    await anyio.to_thread.run_sync(command.upgrade, cfg, "head")
    await init_redis()
    await ensure_buckets()
    yield
    from http_client import close_http_client
    from storage import close_s3

    await close_s3()
    await close_http_client()
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await get_redis().flushdb()
    mailer.OUTBOX.clear()
    yield


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, client=("10.0.0.1", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def client_for_ip(ip: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(ip, 5000)), base_url="http://test"
    )


async def make_user(
    handle: str | None = None,
    *,
    role: Role = Role.user,
    verified: bool = True,
    password: bool = True,
    created_days_ago: int = 30,
    **fields: object,
) -> tuple[User, dict[str, str]]:
    """Insert a user directly and return (user, auth headers) for a fresh session."""
    global _password_hash
    if _password_hash is None:
        _password_hash = await hash_password(TEST_PASSWORD)
    handle = handle or f"user_{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as db:
        user = User(
            id=uuid7(),
            email=f"{handle}@example.com",
            handle=handle,
            password_hash=_password_hash if password else None,
            email_verified_at=utcnow() if verified else None,
            role=role,
            **{"display_name": handle.replace("_", " ").title(), **fields},
        )
        db.add(user)
        db.add(UserSettings(user_id=user.id))
        await db.flush()
        await db.execute(
            text("UPDATE users SET created_at = now() - make_interval(days => :d) WHERE id = :id"),
            {"d": created_days_ago, "id": user.id},
        )
        sid = uuid7()
        _, token_hash = new_refresh_token(sid)
        db.add(
            AuthSession(
                id=sid,
                user_id=user.id,
                token_hash=token_hash,
                expires_at=utcnow() + timedelta(days=30),
            )
        )
        await db.commit()
        await db.refresh(user)
    token = create_access_token(user.id, sid, role.value)
    return user, {"Authorization": f"Bearer {token}"}


CSRF = {"X-Requested-With": "toxic-express"}


async def reset_rate_limits() -> None:
    redis = get_redis()
    keys = [k async for k in redis.scan_iter("rl:*")]
    if keys:
        await redis.delete(*keys)


RANT = {
    "title": "My manager scheduled a meeting about meetings",
    "body": "Three hours of my life, gone. Nobody knew why we were there.",
    "category": "work",
    "tags": ["meetings", "corporate"],
    "frustration_level": 4,
}


async def create_rant(
    client: httpx.AsyncClient, headers: dict[str, str], **overrides: object
) -> dict:
    r = await client.post("/api/v1/posts", json={**RANT, **overrides}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()
