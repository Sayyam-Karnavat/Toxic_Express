import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

import { Spinner } from "./spinner";

// DESIGN.md: button-primary, button-green, button-white, button-ghost, button-ghost-sm
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-xs font-medium whitespace-nowrap transition-[filter,background-color,transform] active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
  {
    variants: {
      variant: {
        primary: "bg-primary text-on-primary rounded-sm hover:brightness-110",
        green: "bg-green text-ink-dark rounded-sm hover:brightness-105",
        white: "bg-ink text-ink-dark rounded-lg hover:brightness-95",
        ghost: "bg-surface-indigo text-ink rounded-lg hover:bg-surface-raised",
        "ghost-sm": "bg-surface-indigo text-ink rounded-xs hover:bg-surface-raised",
        quiet: "bg-transparent text-ink-soft rounded-sm hover:bg-surface-indigo hover:text-ink",
        danger: "bg-surface-indigo text-danger rounded-sm hover:bg-surface-raised",
      },
      size: {
        lg: "text-link-lg px-xl py-lg min-h-11",
        md: "text-link px-xl py-sm min-h-11",
        sm: "text-link-sm px-md py-xs min-h-9",
        icon: "size-10 rounded-full p-0",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, loading, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={asChild ? undefined : disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {asChild ? (
          children
        ) : (
          <>
            {loading && <Spinner className="size-4" />}
            {children}
          </>
        )}
      </Comp>
    );
  },
);
Button.displayName = "Button";
