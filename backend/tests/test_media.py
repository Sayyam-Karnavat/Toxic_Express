import asyncio
import io
import subprocess
from pathlib import Path

import httpx
import pytest
import respx
from PIL import Image
from pydantic import SecretStr

import moderation
from config import settings
from media_processing import ffmpeg_binary
from tests.conftest import RANT, create_rant, make_user


def jpeg_with_gps(size=(1600, 1200)) -> bytes:
    img = Image.new("RGB", size, (200, 40, 90))
    exif = Image.Exif()
    exif[0x010F] = "SpyCam Inc"  # Make
    exif[0x8825] = {1: "N", 2: (12.0, 58.0, 0.0), 3: "E", 4: (77.0, 35.0, 0.0)}  # GPS IFD
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    data = buf.getvalue()
    assert Image.open(io.BytesIO(data)).getexif().get_ifd(0x8825)  # sanity: GPS present
    return data


def make_video(tmp_path: Path, seconds: int = 3) -> bytes:
    out = tmp_path / "in.mp4"
    subprocess.run(
        [
            ffmpeg_binary(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={seconds}:size=640x360:rate=25",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-metadata",
            "title=SECRET-TITLE",
            "-metadata",
            "location=+12.97+077.59/",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(out),
        ],
        check=True,
    )
    return out.read_bytes()


async def upload(
    client: httpx.AsyncClient,
    headers: dict,
    data: bytes,
    mime: str,
    kind: str = "image",
    purpose: str = "post",
) -> dict:
    r = await client.post(
        "/api/v1/media/upload-url",
        headers=headers,
        json={"kind": kind, "purpose": purpose, "mime": mime, "size_bytes": len(data)},
    )
    assert r.status_code == 201, r.text
    ticket = r.json()
    async with httpx.AsyncClient() as s3:
        put = await s3.put(ticket["upload_url"], content=data, headers=ticket["headers"])
        assert put.status_code == 200, put.text
    done = await client.post(f"/api/v1/media/{ticket['media_id']}/complete", headers=headers)
    assert done.status_code == 200, done.text
    return done.json()


async def test_upload_validation(client: httpx.AsyncClient, monkeypatch):
    _, h = await make_user("uploader")
    bad = {"kind": "image", "mime": "image/gif", "size_bytes": 100}
    assert (await client.post("/api/v1/media/upload-url", headers=h, json=bad)).status_code == 400
    big = {"kind": "image", "mime": "image/png", "size_bytes": 11 * 1024 * 1024}
    r = await client.post("/api/v1/media/upload-url", headers=h, json=big)
    assert r.json()["error"]["code"] == "file_too_large"
    vid_avatar = {"kind": "video", "purpose": "avatar", "mime": "video/mp4", "size_bytes": 100}
    assert (
        await client.post("/api/v1/media/upload-url", headers=h, json=vid_avatar)
    ).status_code == 400
    _, unverified = await make_user("unverified", verified=False)
    ok = {"kind": "image", "mime": "image/png", "size_bytes": 100}
    r = await client.post("/api/v1/media/upload-url", headers=unverified, json=ok)
    assert r.json()["error"]["code"] == "email_unverified"
    monkeypatch.setattr(settings, "media_min_account_age_hours", 24)
    _, fresh = await make_user("fresh", created_days_ago=0)
    r = await client.post("/api/v1/media/upload-url", headers=fresh, json=ok)
    assert r.json()["error"]["code"] == "account_too_new"


async def test_presigned_url_enforces_declared_size_and_type(client: httpx.AsyncClient):
    _, h = await make_user("sneaky")
    data = jpeg_with_gps()
    ticket = (
        await client.post(
            "/api/v1/media/upload-url",
            headers=h,
            json={"kind": "image", "mime": "image/jpeg", "size_bytes": len(data)},
        )
    ).json()
    async with httpx.AsyncClient() as s3:
        bigger = await s3.put(
            ticket["upload_url"], content=data + b"x" * 5000, headers=ticket["headers"]
        )
        assert bigger.status_code in (400, 403)
        wrong_type = await s3.put(
            ticket["upload_url"], content=data, headers={"Content-Type": "text/html"}
        )
        assert wrong_type.status_code in (400, 403)
    r = await client.post(f"/api/v1/media/{ticket['media_id']}/complete", headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "upload_missing"


async def test_image_pipeline_strips_exif_and_attaches_to_post(client: httpx.AsyncClient):
    _, h = await make_user("photographer")
    media = await upload(client, h, jpeg_with_gps(), "image/jpeg")
    assert media["state"] == "ready", media
    assert set(media["urls"]) == {"large", "thumb"}
    async with httpx.AsyncClient() as http:
        large = await http.get(media["urls"]["large"])
    assert large.status_code == 200 and large.headers["content-type"] == "image/webp"
    img = Image.open(io.BytesIO(large.content))
    assert img.format == "WEBP" and img.width == 1080
    assert not img.getexif() and "exif" not in img.info and "xmp" not in img.info

    post = await create_rant(client, h, media_ids=[media["id"]])
    assert post["moderation_state"] == "published"
    assert post["media"][0]["urls"]["thumb"].endswith("/thumb.webp")
    reuse = await client.post("/api/v1/posts", headers=h, json={**RANT, "media_ids": [media["id"]]})
    assert reuse.status_code == 404  # media already attached elsewhere
    _, other = await make_user("thief")
    stolen = await client.post(
        "/api/v1/posts", headers=other, json={**RANT, "media_ids": [media["id"]]}
    )
    assert stolen.status_code == 404


async def test_video_pipeline_transcodes_and_strips_metadata(client: httpx.AsyncClient, tmp_path):
    _, h = await make_user("filmmaker")
    media = await upload(client, h, make_video(tmp_path), "video/mp4", kind="video")
    assert media["state"] == "ready", media
    assert set(media["urls"]) == {"video", "poster"}
    assert 2.5 <= media["duration_seconds"] <= 3.5
    async with httpx.AsyncClient() as http:
        video = await http.get(media["urls"]["video"])
    out = tmp_path / "out.mp4"
    out.write_bytes(video.content)
    probe = subprocess.run(
        [ffmpeg_binary(), "-hide_banner", "-i", str(out)], capture_output=True, text=True
    )
    assert "SECRET-TITLE" not in probe.stderr and "location" not in probe.stderr.lower()
    assert "h264" in probe.stderr

    post = await create_rant(client, h, media_ids=[media["id"]])
    assert post["media"][0]["kind"] == "video"
    image = await upload(client, h, jpeg_with_gps((300, 300)), "image/jpeg")
    mixed = await client.post(
        "/api/v1/posts", headers=h, json={**RANT, "media_ids": [media["id"], image["id"]]}
    )
    assert mixed.status_code in (400, 404)


async def test_disguised_files_are_rejected(client: httpx.AsyncClient):
    _, h = await make_user("trickster")
    fake_image = await upload(
        client, h, b"<html><script>alert(1)</script></html>" * 10, "image/png"
    )
    assert fake_image["state"] == "rejected" and fake_image["reject_reason"]
    playlist = (
        b"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:10.0,\nfile:///etc/passwd\n#EXT-X-ENDLIST\n"
    )
    fake_video = await upload(client, h, playlist, "video/mp4", kind="video")
    assert fake_video["state"] == "rejected"
    r = await client.post(
        "/api/v1/posts", headers=h, json={**RANT, "media_ids": [fake_image["id"]]}
    )
    assert r.status_code == 400


async def test_avatar_upload_is_square_and_set_on_profile(client: httpx.AsyncClient):
    _, h = await make_user("selfie")
    media = await upload(client, h, jpeg_with_gps(), "image/jpeg", purpose="avatar")
    assert set(media["urls"]) == {"400", "96"}
    async with httpx.AsyncClient() as http:
        img = Image.open(io.BytesIO((await http.get(media["urls"]["96"])).content))
    assert img.size == (96, 96)
    r = await client.patch("/api/v1/me", headers=h, json={"avatar_media_id": media["id"]})
    assert r.status_code == 200 and r.json()["avatar"]["96"] == media["urls"]["96"]
    post_media = await upload(client, h, jpeg_with_gps((200, 200)), "image/jpeg")
    r = await client.patch("/api/v1/me", headers=h, json={"cover_media_id": post_media["id"]})
    assert r.status_code == 404  # wrong purpose


async def test_flagged_media_sends_post_to_review(client: httpx.AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("sk-test"))
    _, h = await make_user("edgy")
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="test").pass_through()
        mock.route(host="localhost").pass_through()
        mock.post(moderation.OPENAI_MODERATION_URL).respond(
            200, json={"results": [{"category_scores": {"sexual/minors": 0.9}}]}
        )
        media = await upload(client, h, jpeg_with_gps((400, 400)), "image/jpeg")
    assert media["state"] == "rejected"
    r = await client.post("/api/v1/posts", headers=h, json={**RANT, "media_ids": [media["id"]]})
    assert r.status_code == 400


async def test_media_status_is_private(client: httpx.AsyncClient):
    _, h = await make_user("owner_o")
    _, other = await make_user("other_o")
    media = await upload(client, h, jpeg_with_gps((300, 300)), "image/jpeg")
    assert (await client.get(f"/api/v1/media/{media['id']}", headers=h)).status_code == 200
    assert (await client.get(f"/api/v1/media/{media['id']}", headers=other)).status_code == 404


@pytest.mark.parametrize("n", [5])
async def test_pending_upload_cap(client: httpx.AsyncClient, n):
    _, h = await make_user("hoarder")
    ok = {"kind": "image", "mime": "image/png", "size_bytes": 100}
    codes = []
    for _ in range(11):
        from tests.conftest import reset_rate_limits

        await reset_rate_limits()
        codes.append(
            (await client.post("/api/v1/media/upload-url", headers=h, json=ok)).status_code
        )
    assert codes[:10] == [201] * 10 and codes[10] == 429
    await asyncio.sleep(0)
