import type { ReactNode } from "react";

/** DESIGN.md `ex-empty-state-card`. */
export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg bg-surface-indigo p-section text-center">
      <p className="font-display text-heading-sm font-bold uppercase">{title}</p>
      {children && <div className="mx-auto mt-xs max-w-[28rem] text-body text-ink-soft">{children}</div>}
      {action && <div className="mt-xl flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg bg-surface-indigo p-xl text-center">
      <p className="text-body text-danger">{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="mt-sm text-link-sm text-link-cyan underline">
          Try again
        </button>
      )}
    </div>
  );
}
