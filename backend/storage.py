"""S3-compatible object storage (Cloudflare R2 in production).

Uploads go browser -> R2 directly via presigned PUT URLs; the API never proxies media bytes.
`uploads-raw` is private and short-lived, `media-public` holds processed, metadata-free files.
"""

import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from config import settings

logger = logging.getLogger(__name__)

_stack: AsyncExitStack | None = None
_client: Any = None

_BOTO_CONFIG = Config(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    retries={"max_attempts": 5, "mode": "adaptive"},
    connect_timeout=5,
    read_timeout=60,
)


async def get_s3() -> Any:
    global _stack, _client
    if _client is None:
        _stack = AsyncExitStack()
        session = aioboto3.Session()
        _client = await _stack.enter_async_context(
            session.client(  # pyright: ignore[reportArgumentType]
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
                region_name=settings.s3_region,
                config=_BOTO_CONFIG,
            )
        )
    return _client


async def close_s3() -> None:
    global _stack, _client
    if _stack is not None:
        await _stack.aclose()
    _stack, _client = None, None


def public_url(key: str) -> str:
    return f"{settings.media_public_base_url.rstrip('/')}/{key}"


def public_urls(variants: dict[str, str] | None) -> dict[str, str]:
    return {name: public_url(key) for name, key in (variants or {}).items()}


async def presign_put(key: str, content_type: str, content_length: int) -> str:
    """Content-Type and Content-Length are signed, so the client cannot change type or size."""
    s3 = await get_s3()
    return await s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket_raw,
            "Key": key,
            "ContentType": content_type,
            "ContentLength": content_length,
        },
        ExpiresIn=settings.upload_url_ttl_seconds,
    )


async def head(bucket: str, key: str) -> dict[str, Any] | None:
    s3 = await get_s3()
    try:
        return await s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


async def download(bucket: str, key: str, dest: Path, max_bytes: int) -> int:
    s3 = await get_s3()
    response = await s3.get_object(Bucket=bucket, Key=key)
    total = 0
    with dest.open("wb") as fh:
        async for chunk in response["Body"].iter_chunks(1024 * 256):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("object exceeds the allowed size")
            fh.write(chunk)
    return total


async def upload_file(key: str, path: Path, content_type: str) -> None:
    s3 = await get_s3()
    with path.open("rb") as fh:
        await s3.put_object(
            Bucket=settings.s3_bucket_public,
            Key=key,
            Body=fh,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )


async def delete_keys(bucket: str, keys: list[str]) -> None:
    if not keys:
        return
    s3 = await get_s3()
    for i in range(0, len(keys), 1000):
        batch = [{"Key": k} for k in keys[i : i + 1000]]
        await s3.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})


async def ensure_buckets() -> None:
    """Dev/test convenience: create buckets if missing. In production they are provisioned in R2."""
    s3 = await get_s3()
    for bucket in (settings.s3_bucket_raw, settings.s3_bucket_public):
        try:
            await s3.head_bucket(Bucket=bucket)
        except ClientError:
            await s3.create_bucket(Bucket=bucket)
            logger.info("created bucket %s", bucket)
