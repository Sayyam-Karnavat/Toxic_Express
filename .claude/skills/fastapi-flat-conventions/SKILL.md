---
name: fastapi-flat-conventions
description: Conventions for adding or changing Toxic-Express backend endpoints, services, models or migrations (flat FastAPI layout, layering, schemas, errors, pagination, rate limits, tests). Use for any backend/ change.
---

# Toxic-Express backend conventions

## New endpoint checklist
1. Request/response schemas in `schemas.py` (`class FooIn(In)`, `class FooOut(BaseModel)`); text
   fields use the `Line`/`Paragraph` annotated types so they are sanitised.
2. Business logic in the matching `*_service.py` (create one if the domain is new; keep files flat).
3. Thin route in `*_routes.py`: auth dependency (`CurrentUser`, `ActiveUser`, `OptionalUser`,
   `ModUser`), `dependencies=[Depends(rate_limit("name", limit, window, "user"))]` for writes,
   `response_model=...`. Register new routers in `main.py`.
4. Lists: keyset pagination (`decode_cursor` + `keyset_before`), `limit + 1` to detect `next_cursor`.
5. Avoid N+1: `selectinload` relationships (they are `lazy="raise"`), batch per-viewer lookups.
6. Visibility: respect blocks/mutes via `social_service.load_viewer_ctx`; published-only for others.
7. Anonymity: if the entity can be anonymous, return the `Anon*Out` variant with no author fields.
8. Tests in `tests/test_<domain>.py` using `make_user()` / `create_rant()` from `conftest.py`:
   happy path, 401/403, 422 validation, plus anonymity if relevant.
9. `uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest`.
10. Regenerate frontend types: `cd frontend && npm run gen:api`.

## Migrations
`uv run alembic revision --autogenerate -m "msg"`, review (circular FKs need `op.create_foreign_key`
after both tables), `uv run alembic upgrade head`, then `uv run alembic check` must say no changes.
