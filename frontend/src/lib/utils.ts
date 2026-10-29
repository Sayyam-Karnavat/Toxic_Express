import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Teach tailwind-merge the DESIGN.md scale so `text-link-sm` (a font size) never cancels
// `text-ink-dark` (a colour), and radius/spacing tokens merge correctly.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [
        { text: ["display-xl", "display-lg", "display-md", "heading-lg", "heading-sm", "body-lg", "link-lg", "body", "link", "link-sm"] },
      ],
      "text-color": [
        {
          text: [
            "primary", "on-primary", "green", "magenta", "magenta-strong", "link-cyan", "canvas", "surface-indigo",
            "surface-onyx", "surface-black", "surface-raised", "ink", "ink-dark", "ink-soft", "ink-faint", "muted",
            "hairline", "danger", "indigo-line", "google-text",
          ],
        },
      ],
      rounded: [{ rounded: ["xs", "sm", "md", "lg", "xl", "pill", "jumbo", "full"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31536000],
  ["month", 2592000],
  ["week", 604800],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];
const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto", style: "short" });

export function timeAgo(iso: string): string {
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

export function compactNumber(n: number): string {
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function formatBytes(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}
