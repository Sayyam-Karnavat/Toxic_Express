import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <Link to="/" className={cn("group inline-flex items-center gap-xs", className)} aria-label="Toxic-Express home">
      <span aria-hidden className="relative inline-flex size-9 items-center justify-center rounded-sm bg-primary">
        <span className="font-display text-link-lg font-bold leading-none">T</span>
        <span className="absolute -bottom-0.5 -right-0.5 size-3 rounded-full border-2 border-canvas bg-green" />
      </span>
      <span className="font-display text-link-lg font-bold uppercase tracking-tight">Toxic-Express</span>
    </Link>
  );
}
