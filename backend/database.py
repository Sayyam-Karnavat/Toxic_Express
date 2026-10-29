"""Async SQLAlchemy engine and the per-request session dependency."""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings


def _engine_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "connect_args": {"server_settings": {"application_name": "toxic-express"}},
    }
    if settings.db_use_pgbouncer:
        # Transaction-mode poolers cannot keep prepared statements across transactions.
        kwargs["connect_args"]["statement_cache_size"] = 0
        kwargs["connect_args"]["prepared_statement_cache_size"] = 0
    return kwargs


engine = create_async_engine(settings.database_url, **_engine_kwargs())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
