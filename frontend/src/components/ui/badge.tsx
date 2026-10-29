import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

// DESIGN.md `badge`: magenta chip. Small white text uses magenta-strong for AA contrast.
const badgeVariants = cva(
  "inline-flex items-center gap-xxs rounded-lg px-sm py-xxs text-link-sm font-medium",
  {
    variants: {
      variant: {
        magenta: "bg-magenta-strong text-ink",
        primary: "bg-primary text-on-primary",
        green: "bg-green text-ink-dark",
        outline: "border border-indigo-line text-ink-soft",
        dark: "bg-canvas text-ink-soft",
      },
    },
    defaultVariants: { variant: "magenta" },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
