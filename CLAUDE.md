# Toxic-Express: working notes for Claude

Social app for venting ("rants"), relating and solving. See README.md for running/testing.

## Hard rules
- **Backend is flat**: application code is one file per module in `backend/`. The only folders are
  `migrations/` (Alembic) and `tests/`. Layering: `*_routes.py` (thin HTTP) -> `*_service.py`
  (business logic) -> `models.py`/`database.py`. Shared deps in `deps.py`, errors in `errors.py`.
- **Frontend follows DESIGN.md.** Use tokens from `frontend/src/styles/tokens.css` only; no hex
  colours anywhere else (`npm run check:tokens` enforces it). Display type is Space Grotesk, ALL CAPS
  for headlines; body is Inter. Green (`bg-green`) is for the single highest-intent CTA per screen.
  Never use Discord's name, logo, fonts or art. The crisis/self-harm UI stays calm (no caps/gradients).
- **Anonymity is structural**: anonymous posts/comments serialise through `AnonPostOut` /
  `AnonCommentOut`, which have no author fields. Never add author data to them. Anonymous posts never
  appear via "following a user" (only via topics). `tests/test_anonymity.py` must keep passing.
- **Moderation is fail-safe**: if the moderation API is unavailable, content stays `pending` and the
  worker retries; never publish unchecked content.

## Backend conventions
- Pydantic models for every request (`In`, `extra="forbid"`) and response; never return ORM objects.
- Errors: raise `AppError` (or helpers in `errors.py`); responses are `{"error": {code, message, details}}`.
- Every write endpoint has a `rate_limit(...)` dependency; writes require `ActiveUser`.
- Relationships are `lazy="raise"`: eager-load with `selectinload`; hydrate lists in batches.
- Keyset pagination via `utils.keyset_before/after` + `encode_cursor`; never OFFSET (search is bounded).
- Counters change through SQL `UPDATE ... SET x = x + 1`; reload with `populate_existing` when needed.
- Calls to external services go through `retry.http_retry`; user-supplied URLs only via `safe_fetch.py`.
- Schema change -> `uv run alembic revision --autogenerate -m "..."`, review it, `alembic check` must be clean.
- Each endpoint gets tests for: happy path, auth failure, validation. Run `uv run pytest`.

## Frontend conventions
- Server state only in TanStack Query (`src/api/*`); query keys in `src/api/keys.ts`; after a post
  mutation call `patchPost`. Client state: `src/store/auth.ts` (access token in memory only).
- All HTTP through `lib/api.ts` (`api<T>()`), which handles refresh, CSRF header and error shape.
- TypeScript strict, no `any`; API types come from `src/types` (generated: `npm run gen:api`).
- Components < ~200 lines; accessible names on all controls; touch targets >= 44px; mobile first.
