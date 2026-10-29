"""/feed and /users/{handle}/posts."""

from typing import Literal

from fastapi import APIRouter, Query

import feed
from deps import DB, CurrentUser, OptionalUser
from models import Category
from schemas import PostPage

router = APIRouter(tags=["feed"])

Cursor = Query(None, max_length=200)


@router.get("/feed/following", response_model=PostPage)
async def following(user: CurrentUser, db: DB, cursor: str | None = Cursor) -> PostPage:
    return await feed.following(db, user, cursor)


@router.get("/feed", response_model=PostPage)
async def public_feed(
    viewer: OptionalUser,
    db: DB,
    sort: Literal["latest", "trending", "solved"] = "latest",
    category: Category | None = None,
    tag: str | None = Query(None, pattern=r"^[a-z0-9][a-z0-9-]{0,28}[a-z0-9]$"),
    cursor: str | None = Cursor,
) -> PostPage:
    if sort == "trending":
        return await feed.trending(db, viewer, cursor, category)
    if sort == "solved":
        return await feed.solved(db, viewer, cursor)
    return await feed.latest(db, viewer, cursor, category, tag)


@router.get("/users/{handle}/posts", response_model=PostPage)
async def user_posts(
    handle: str, viewer: OptionalUser, db: DB, cursor: str | None = Cursor
) -> PostPage:
    return await feed.user_posts(db, handle, viewer, cursor)
