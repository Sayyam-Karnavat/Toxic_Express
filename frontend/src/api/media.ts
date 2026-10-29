import { api, ApiError } from "@/lib/api";
import type { Media, UploadTicket } from "@/types";

export type MediaPurpose = "post" | "avatar" | "cover";

const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"];
const VIDEO_TYPES = ["video/mp4", "video/quicktime", "video/webm"];
const MB = 1024 * 1024;

export function mediaKind(file: File): "image" | "video" | null {
  if (IMAGE_TYPES.includes(file.type)) return "image";
  if (VIDEO_TYPES.includes(file.type)) return "video";
  return null;
}

function videoDuration(file: File): Promise<number> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    video.onloadedmetadata = () => {
      URL.revokeObjectURL(url);
      resolve(video.duration);
    };
    video.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(0); // let the server decide
    };
    video.src = url;
  });
}

/** Client-side checks mirror the server limits for fast feedback; the server re-validates. */
export async function validateFile(file: File, purpose: MediaPurpose): Promise<string | null> {
  const kind = mediaKind(file);
  if (!kind) return "Use JPEG, PNG, WebP or HEIC images, or MP4, MOV or WebM videos.";
  if (purpose !== "post" && kind !== "image") return "Profile pictures must be images.";
  if (kind === "image" && file.size > 10 * MB) return "Images can be up to 10 MB.";
  if (kind === "video" && file.size > 50 * MB) return "Videos can be up to 50 MB.";
  if (kind === "video" && (await videoDuration(file)) > 61) return "Videos can be up to 60 seconds.";
  return null;
}

function putWithProgress(url: string, file: File, headers: Record<string, string>, onProgress: (p: number) => void) {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new ApiError(xhr.status, "upload_failed", "Upload failed. Please try again."));
    xhr.onerror = () => reject(new ApiError(0, "upload_failed", "Upload failed. Check your connection."));
    xhr.send(file);
  });
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Presigned direct-to-storage upload, then poll until processing (re-encode + moderation) ends. */
export async function uploadMedia(
  file: File,
  purpose: MediaPurpose,
  onProgress: (p: number) => void = () => {},
): Promise<Media> {
  const kind = mediaKind(file);
  if (!kind) throw new ApiError(400, "unsupported_type", "Unsupported file type");
  const ticket = await api<UploadTicket>("/media/upload-url", {
    method: "POST",
    body: { kind, purpose, mime: file.type, size_bytes: file.size },
  });
  let attempt = 0;
  for (;;) {
    try {
      await putWithProgress(ticket.upload_url, file, ticket.headers, onProgress);
      break;
    } catch (err) {
      if (++attempt >= 3) throw err;
      await sleep(500 * 2 ** attempt);
    }
  }
  let media = await api<Media>(`/media/${ticket.media_id}/complete`, { method: "POST" });
  const deadline = Date.now() + (kind === "video" ? 180_000 : 60_000);
  let delay = 800;
  while (media.state === "processing" && Date.now() < deadline) {
    await sleep(delay);
    delay = Math.min(delay * 1.5, 4000);
    media = await api<Media>(`/media/${ticket.media_id}`);
  }
  if (media.state === "rejected") {
    throw new ApiError(422, "media_rejected", media.reject_reason ?? "This file can't be used.");
  }
  return media;
}
