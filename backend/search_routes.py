"""/search across rants, people and tags."""

from typing import Literal

from fastapi import APIRouter, Depends, Query

import feed
from deps import DB, OptionalUser, rate_limit
from schemas import SearchOut

router = APIRouter(tags=["search"])


@router.get(
    "/search",
    response_model=SearchOut,
    dependencies=[Depends(rate_limit("search", 60, 60, "user"))],
)
async def search(
    viewer: OptionalUser,
    db: DB,
    q: str = Query(min_length=2, max_length=100),
    type: Literal["all", "posts", "users", "tags"] = "all",
    cursor: str | None = Query(None, max_length=200),
) -> SearchOut:
    return await feed.search(db, viewer, q, type, cursor)
