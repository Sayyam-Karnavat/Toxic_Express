"""Comments on posts, replies and helpful votes."""

import uuid

from fastapi import APIRouter, Depends, Query

import comments_service
from deps import DB, ActiveUser, OptionalUser, rate_limit
from schemas import AnyCommentOut, CommentCreateIn, CommentPage, CommentUpdateIn, OkOut

router = APIRouter(tags=["comments"])


@router.get("/posts/{post_id}/comments", response_model=CommentPage)
async def list_comments(
    post_id: uuid.UUID,
    viewer: OptionalUser,
    db: DB,
    cursor: str | None = Query(None, max_length=200),
) -> CommentPage:
    return await comments_service.list_comments(db, post_id, viewer, cursor)


@router.post(
    "/posts/{post_id}/comments",
    response_model=AnyCommentOut,
    status_code=201,
    dependencies=[Depends(rate_limit("comment_create", 60, 3600, "user"))],
)
async def create_comment(
    post_id: uuid.UUID, data: CommentCreateIn, user: ActiveUser, db: DB
) -> AnyCommentOut:
    return await comments_service.create_comment(db, user, post_id, data)


@router.get("/comments/{comment_id}", response_model=AnyCommentOut)
async def get_comment(comment_id: uuid.UUID, viewer: OptionalUser, db: DB) -> AnyCommentOut:
    return await comments_service.get_comment(db, comment_id, viewer)


@router.get("/comments/{comment_id}/replies", response_model=CommentPage)
async def list_replies(
    comment_id: uuid.UUID,
    viewer: OptionalUser,
    db: DB,
    cursor: str | None = Query(None, max_length=200),
) -> CommentPage:
    return await comments_service.list_replies(db, comment_id, viewer, cursor)


@router.patch(
    "/comments/{comment_id}",
    response_model=AnyCommentOut,
    dependencies=[Depends(rate_limit("comment_update", 60, 3600, "user"))],
)
async def update_comment(
    comment_id: uuid.UUID, data: CommentUpdateIn, user: ActiveUser, db: DB
) -> AnyCommentOut:
    return await comments_service.update_comment(db, user, comment_id, data)


@router.delete("/comments/{comment_id}", response_model=OkOut)
async def delete_comment(comment_id: uuid.UUID, user: ActiveUser, db: DB) -> OkOut:
    await comments_service.delete_comment(db, user, comment_id)
    return OkOut()


@router.put(
    "/comments/{comment_id}/helpful",
    response_model=AnyCommentOut,
    dependencies=[Depends(rate_limit("helpful", 200, 3600, "user"))],
)
async def mark_helpful(comment_id: uuid.UUID, user: ActiveUser, db: DB) -> AnyCommentOut:
    return await comments_service.set_helpful(db, user, comment_id, True)


@router.delete(
    "/comments/{comment_id}/helpful",
    response_model=AnyCommentOut,
    dependencies=[Depends(rate_limit("helpful", 200, 3600, "user"))],
)
async def unmark_helpful(comment_id: uuid.UUID, user: ActiveUser, db: DB) -> AnyCommentOut:
    return await comments_service.set_helpful(db, user, comment_id, False)
