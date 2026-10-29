---
name: react-conventions
description: Conventions for Toxic-Express frontend work (React + TanStack Query + Tailwind v4 themed by DESIGN.md). Use for any frontend/ change: new pages, components, styling or API hooks.
---

# Toxic-Express frontend conventions

## Styling (DESIGN.md)
- Only tokens from `src/styles/tokens.css`: colours `canvas`, `surface-indigo`, `primary` (Blurple),
  `green` (one high-intent CTA per screen), `magenta`/`magenta-strong` (small text on magenta),
  `link-cyan`, `ink`, `ink-soft`, `ink-faint`, `danger`; type `text-display-*`, `text-heading-*`,
  `text-body`, `text-link*`; radii `rounded-sm/lg/xl/pill`; spacing `p-xl`, `gap-md`, etc.
- Avoid `max-w-{xs..xl}` / `w-{xs..xl}` (they resolve to spacing tokens); use `max-w-[28rem]`.
- Headlines: `font-display font-bold uppercase`. Cards: `rounded-lg bg-surface-indigo p-xl`.
- Use `cn()` from `lib/utils.ts` (configured for the custom scale). Run `npm run check:tokens`.

## Data
- Hooks live in `src/api/<domain>.ts`, keys in `src/api/keys.ts`, HTTP via `api<T>()`.
- Mutations returning a post -> `patchPost(qc, post)`; otherwise invalidate the narrowest key.
- Viewer-specific queries must not run before auth resolves (`useAuth().status`).

## Quality bar
- Accessible names on every control (`aria-label` for icon buttons), labels for inputs, 44px targets.
- No `dangerouslySetInnerHTML`; render user text via `<Markdown>`.
- `npx tsc -b && npm run lint && npm test`; for UI changes also run the Playwright suite.
