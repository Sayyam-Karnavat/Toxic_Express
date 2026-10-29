# Toxic-Express

A social network for frustrated people: **rant** about a problem (optionally anonymously),
**relate** with people who've been there, and **resolve** it by pinning the comment that helped.

- **Backend:** FastAPI · PostgreSQL · Redis (cache, rate limits, arq job queue) · S3/Cloudflare R2 · ffmpeg
- **Frontend:** React 18 · TypeScript · Vite · Tailwind v4 · TanStack Query · Radix. Design system: [DESIGN.md](DESIGN.md)
- **Auth:** email + password and Google (OAuth 2.0 / OIDC, server-side code flow with PKCE)
- **Moderation:** local rules (personal-info detection, blocklist) + OpenAI omni-moderation (text, images, video frames) + reports, strikes and appeals

## Layout

```
backend/    flat FastAPI app: *_routes.py -> *_service.py -> models.py (+ migrations/, tests/)
frontend/   React app (src/api data hooks, src/components, src/pages, src/styles/tokens.css)
infra/      dev S3 config, R2 CORS policy
docker-compose.yml        dev infra: Postgres :5433, Redis :6380, SeaweedFS S3 :8333
docker-compose.prod.yml   VM deployment: api, worker, redis, caddy
```

## Run locally

Requires Docker, [uv](https://docs.astral.sh/uv/) and Node 22.

```bash
docker compose up -d                                   # Postgres, Redis, S3
cd backend
cp .env.example .env                                   # dev defaults work as-is
uv sync && uv run alembic upgrade head
uv run uvicorn main:app --reload --port 8000           # API (docs at /api/docs)
uv run arq worker.WorkerSettings                       # worker, in a second terminal
cd ../frontend && npm ci && npm run dev                # http://localhost:5173
```

Without `RESEND_API_KEY`, emails (verification, password reset) are printed in the worker log.
Without `OPENAI_API_KEY`, only the local moderation rules run (the key is mandatory in prod).
For Google sign-in, create an OAuth client and add `http://localhost:5173/api/v1/auth/google/callback`
as an authorised redirect URI.

To make yourself a moderator: `UPDATE users SET role = 'admin' WHERE handle = 'you';`

## Tests

```bash
cd backend && uv run pytest                    # 137 tests: API, anonymity, moderation, media (real S3 + ffmpeg)
uv run ruff check . && uv run pyright
cd ../frontend && npm test && npm run lint && npx tsc -b && npm run check:tokens
E2E_EMAIL_LOG=/path/to/worker.log npx playwright test   # needs the full stack running
```

After changing backend schemas, regenerate frontend types with `npm run gen:api`.

## Deploy (free tier)

| Piece | Where |
|---|---|
| API + worker + Redis + Caddy | Any VM with Docker (Oracle Cloud Always Free): `API_DOMAIN=api.example.com docker compose -f docker-compose.prod.yml up -d --build` |
| Postgres | Neon (set `DB_USE_PGBOUNCER=true` with the pooled URL) |
| Media | Cloudflare R2: buckets `te-uploads-raw` (private, lifecycle: delete after 1 day) and `te-media-public` (custom domain). Apply `infra/r2-cors.json` to the raw bucket. |
| Frontend | Cloudflare Pages: build `npm run build`, output `dist`, env `VITE_API_URL=https://api.example.com/api/v1`. Edit domains in `public/_headers`. |

Production `.env`: `ENV=prod`, a strong `JWT_SECRET`, `COOKIE_SECURE=true`, `CORS_ORIGINS=["https://example.com"]`,
`FRONTEND_URL`, `GOOGLE_REDIRECT_URI=https://api.example.com/api/v1/auth/google/callback`, R2 and OpenAI keys.
The app refuses to start in prod with insecure settings.
