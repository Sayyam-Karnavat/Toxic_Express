import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

/** DESIGN.md `ex-modal-card`: canvas surface, rounded.lg, elevated violet shadow. */
export function DialogContent({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-surface-black/70 backdrop-blur-sm" />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[calc(100vw-32px)] max-w-[36rem] -translate-x-1/2 -translate-y-1/2 overflow-y-auto",
          "rounded-lg border border-indigo-line bg-canvas p-xl shadow-modal focus:outline-none",
          className,
        )}
      >
        <div className="mb-md flex items-start justify-between gap-md">
          <div>
            <DialogPrimitive.Title className="font-display text-heading-sm font-bold uppercase">
              {title}
            </DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-xxs text-link-sm text-ink-soft">
                {description}
              </DialogPrimitive.Description>
            ) : (
              <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close
            className="rounded-full p-xs text-ink-soft hover:bg-surface-indigo hover:text-ink"
            aria-label="Close"
          >
            <X className="size-5" />
          </DialogPrimitive.Close>
        </div>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
