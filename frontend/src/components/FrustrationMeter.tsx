import { cn } from "@/lib/utils";

const LABELS = ["", "Mildly annoyed", "Irritated", "Fed up", "Furious", "Volcanic"];
// Stays inside the DESIGN.md chord: cyan link -> Blurple -> magenta. No fourth loud accent.
const COLOURS = ["", "bg-link-cyan", "bg-link-cyan", "bg-primary", "bg-magenta", "bg-magenta"];

export function FrustrationMeter({ level, compact }: { level: number; compact?: boolean }) {
  return (
    <div className="flex items-center gap-xs" title={`Frustration ${level}/5: ${LABELS[level]}`}>
      <div className="flex gap-0.5" role="img" aria-label={`Frustration level ${level} of 5, ${LABELS[level]}`}>
        {[1, 2, 3, 4, 5].map((i) => (
          <span
            key={i}
            className={cn("h-2 rounded-full", compact ? "w-3" : "w-5", i <= level ? COLOURS[level] : "bg-indigo-line")}
          />
        ))}
      </div>
      {!compact && <span className="text-link-sm text-ink-soft">{LABELS[level]}</span>}
    </div>
  );
}

export function FrustrationPicker({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div role="radiogroup" aria-label="Frustration level" className="flex flex-wrap gap-xs">
      {[1, 2, 3, 4, 5].map((i) => (
        <button
          key={i}
          type="button"
          role="radio"
          aria-checked={value === i}
          onClick={() => onChange(i)}
          className={cn(
            "flex min-h-11 items-center gap-xs rounded-sm border px-sm text-link-sm",
            value === i ? "border-primary bg-surface-raised text-ink" : "border-indigo-line text-ink-soft",
          )}
        >
          <span className={cn("size-3 rounded-full", COLOURS[i])} />
          {i} · {LABELS[i]}
        </button>
      ))}
    </div>
  );
}
