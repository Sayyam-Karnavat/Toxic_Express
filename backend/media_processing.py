"""Media pipeline run by the worker: verify, re-encode, strip metadata, moderate, publish.

Images: Pillow re-encode to WebP (EXIF/GPS dropped). Videos: ffmpeg -> H.264 MP4 with metadata
removed, poster frame and sampled frames for moderation. Raw uploads are deleted afterwards.
"""

import asyncio
import io
import logging
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

import storage
from config import settings
from models import MediaKind, MediaPurpose

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 50_000_000  # decompression-bomb guard (raises above 2x this)

logger = logging.getLogger(__name__)

MB = 1024 * 1024
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/webm"}
MAX_IMAGE_BYTES = 10 * MB
MAX_VIDEO_BYTES = 50 * MB
MAX_VIDEO_SECONDS = 60
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}
FFMPEG_TIMEOUT = 300

# Variant name -> (max width, max height, square crop)
IMAGE_VARIANTS: dict[MediaPurpose, dict[str, tuple[int, int, bool]]] = {
    MediaPurpose.post: {"large": (1080, 1350, False), "thumb": (400, 500, False)},
    MediaPurpose.avatar: {"400": (400, 400, True), "96": (96, 96, True)},
    MediaPurpose.cover: {"large": (1500, 500, False), "thumb": (600, 200, False)},
}


class MediaRejectedError(Exception):
    """The file is invalid or not allowed. The message is safe to show to the uploader."""


def limits_for(kind: MediaKind) -> tuple[set[str], int]:
    return (
        (IMAGE_MIMES, MAX_IMAGE_BYTES)
        if kind == MediaKind.image
        else (VIDEO_MIMES, MAX_VIDEO_BYTES)
    )


@dataclass
class ProcessedMedia:
    files: dict[str, tuple[Path, str]] = field(default_factory=dict)  # variant -> (path, mime)
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    moderation_frames: list[bytes] = field(default_factory=list)  # small JPEGs


# --- Images ------------------------------------------------------------------------------------


def _jpeg_preview(img: Image.Image, size: int = 512) -> bytes:
    preview = img.copy()
    preview.thumbnail((size, size))
    buf = io.BytesIO()
    preview.convert("RGB").save(buf, "JPEG", quality=80)
    return buf.getvalue()


def process_image(src: Path, purpose: MediaPurpose, workdir: Path) -> ProcessedMedia:
    try:
        with Image.open(src) as opened:
            if opened.format not in ALLOWED_IMAGE_FORMATS:
                raise MediaRejectedError("Unsupported image format")
            opened.seek(0)  # first frame of animated images only
            img = ImageOps.exif_transpose(opened)
            img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise MediaRejectedError("This file is not a valid image") from exc

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if has_alpha else "RGB")
    out = ProcessedMedia(width=img.width, height=img.height)
    for name, (max_w, max_h, square) in IMAGE_VARIANTS[purpose].items():
        if square or purpose == MediaPurpose.cover:
            variant = ImageOps.fit(img, (max_w, max_h), Image.Resampling.LANCZOS)
        else:
            variant = img.copy()
            variant.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)  # never upscales
        path = workdir / f"{name}.webp"
        # A fresh save carries no EXIF/XMP/ICC metadata: location and device info are gone.
        variant.save(path, "WEBP", quality=82, method=4)
        out.files[name] = (path, "image/webp")
    out.moderation_frames.append(_jpeg_preview(img))
    return out


# --- Video -------------------------------------------------------------------------------------


def ffmpeg_binary() -> str:
    if settings.ffmpeg_path:
        return settings.ffmpeg_path
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


async def _run_ffmpeg(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_binary(),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), FFMPEG_TIMEOUT)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise MediaRejectedError("Video took too long to process") from None
    if proc.returncode != 0:
        logger.info("ffmpeg failed: %s", stderr.decode(errors="replace")[-500:])
        raise MediaRejectedError("This video could not be processed")
    return stderr.decode(errors="replace")


def sniff_video_container(path: Path) -> str:
    """Pick the demuxer from magic bytes so ffmpeg never auto-detects playlists (SSRF/LFI)."""
    with path.open("rb") as fh:
        head = fh.read(64)
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mov"  # mp4 / mov / m4v share the ISO BMFF demuxer
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "matroska"  # webm / mkv
    raise MediaRejectedError("Unsupported video format")


async def probe_video(path: Path, demuxer: str) -> tuple[float, int, int]:
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_binary(),
        "-hide_banner",
        "-nostdin",
        "-protocol_whitelist",
        "file",
        "-f",
        demuxer,
        "-i",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_bytes = await asyncio.wait_for(proc.communicate(), 60)
    info = stderr_bytes.decode(errors="replace")
    duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", info)
    video = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", info)
    if not duration or not video:
        raise MediaRejectedError("This file is not a valid video")
    h, m, s = duration.groups()
    return int(h) * 3600 + int(m) * 60 + float(s), int(video.group(1)), int(video.group(2))


async def process_video(src: Path, workdir: Path) -> ProcessedMedia:
    demuxer = sniff_video_container(src)
    duration, _, _ = await probe_video(src, demuxer)
    if duration > MAX_VIDEO_SECONDS + 1:
        raise MediaRejectedError(f"Videos can be at most {MAX_VIDEO_SECONDS} seconds")
    out_path = workdir / "video.mp4"
    longest = "if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(1280,ih))"
    await _run_ffmpeg(
        "-protocol_whitelist",
        "file",
        "-f",
        demuxer,
        "-i",
        str(src),
        "-t",
        str(MAX_VIDEO_SECONDS),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-vf",
        f"scale='{longest}',fps=30",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "26",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-threads",
        "2",
        str(out_path),
    )
    poster_jpg = workdir / "poster.jpg"
    await _run_ffmpeg(
        "-ss",
        str(min(1.0, duration / 2)),
        "-i",
        str(out_path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(poster_jpg),
    )
    frames_dir = workdir / "frames"
    frames_dir.mkdir()
    await _run_ffmpeg(
        "-i",
        str(out_path),
        "-vf",
        "fps=1/5,scale=512:-2",
        "-frames:v",
        "12",
        "-q:v",
        "5",
        str(frames_dir / "f_%02d.jpg"),
    )

    result = ProcessedMedia(duration=round(duration, 2))
    result.files["video"] = (out_path, "video/mp4")
    with Image.open(poster_jpg) as poster:
        result.width, result.height = poster.width, poster.height
        poster_webp = workdir / "poster.webp"
        poster.convert("RGB").save(poster_webp, "WEBP", quality=80)
        result.files["poster"] = (poster_webp, "image/webp")
        result.moderation_frames.append(_jpeg_preview(poster))
    result.moderation_frames.extend(p.read_bytes() for p in sorted(frames_dir.glob("*.jpg")))
    return result


# --- Orchestration helpers used by worker jobs -------------------------------------------------


def variant_key(media_id: uuid.UUID, name: str, mime: str) -> str:
    ext = {"image/webp": "webp", "video/mp4": "mp4"}[mime]
    return f"m/{media_id}/{name}.{ext}"


async def upload_variants(media_id: uuid.UUID, processed: ProcessedMedia) -> dict[str, str]:
    keys: dict[str, str] = {}
    for name, (path, mime) in processed.files.items():
        key = variant_key(media_id, name, mime)
        await storage.upload_file(key, path, mime)
        keys[name] = key
    return keys


def new_workdir() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix="te-media-")
