import { EyeOff } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";
import type { Media } from "@/types";

export function PostMedia({ media, sensitive }: { media: Media[]; sensitive: boolean }) {
  const [revealed, setRevealed] = useState(!sensitive);
  const ready = media.filter((m) => m.state === "ready");
  if (!ready.length) return null;
  const video = ready.find((m) => m.kind === "video");

  return (
    <div className="relative mt-md overflow-hidden rounded-lg bg-surface-black">
      <div className={cn(!revealed && "pointer-events-none blur-2xl")} aria-hidden={!revealed}>
        {video ? (
          <video
            controls
            preload="metadata"
            playsInline
            poster={video.urls.poster}
            src={video.urls.video}
            className="max-h-[540px] w-full"
          />
        ) : (
          <div className={cn("grid gap-0.5", ready.length > 1 && "grid-cols-2")}>
            {ready.map((m, i) => (
              <a
                key={m.id}
                href={m.urls.large}
                target="_blank"
                rel="noreferrer"
                className={cn(ready.length === 3 && i === 0 && "row-span-2")}
              >
                <img
                  src={ready.length > 1 ? m.urls.thumb : m.urls.large}
                  alt="Image attached to the rant"
                  loading="lazy"
                  width={m.width ?? undefined}
                  height={m.height ?? undefined}
                  className="h-full max-h-[540px] w-full object-cover"
                />
              </a>
            ))}
          </div>
        )}
      </div>
      {!revealed && (
        <button
          type="button"
          onClick={() => setRevealed(true)}
          className="absolute inset-0 flex flex-col items-center justify-center gap-xs bg-canvas/40 text-body"
        >
          <EyeOff className="size-6" aria-hidden />
          Sensitive content. Tap to view.
        </button>
      )}
    </div>
  );
}
