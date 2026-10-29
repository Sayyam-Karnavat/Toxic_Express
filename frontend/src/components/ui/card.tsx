import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/** DESIGN.md `feature-card-dark`, scaled down to rounded.lg for dense app surfaces. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-lg bg-surface-indigo p-xl", className)} {...props} />;
}

export function SectionTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn("font-display text-heading-sm font-bold uppercase tracking-tight", className)}
      {...props}
    />
  );
}
