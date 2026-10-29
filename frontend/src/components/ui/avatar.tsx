import { cn } from "@/lib/utils";

const SIZES = { sm: "size-8 text-link-sm", md: "size-10 text-link", lg: "size-24 text-heading-sm" };

export function Avatar({
  src,
  name,
  size = "md",
  className,
}: {
  src?: string | null | undefined;
  name: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const initials = name
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return src ? (
    <img src={src} alt="" className={cn("shrink-0 rounded-full object-cover", SIZES[size], className)} loading="lazy" />
  ) : (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full bg-primary font-display font-bold",
        SIZES[size],
        className,
      )}
    >
      {initials || "?"}
    </span>
  );
}

export function AnonAvatar({ size = "md" }: { size?: keyof typeof SIZES }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full border border-dashed border-ink-faint bg-canvas font-display font-bold text-ink-soft",
        SIZES[size],
      )}
    >
      ?
    </span>
  );
}
