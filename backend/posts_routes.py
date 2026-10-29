"""/posts: create, read, edit, delete, react, solve."""

import uuid

from fastapi import APIRouter, Depends

import posts_service
from deps import DB, ActiveUser, OptionalUser, rate_limit
from schemas import AnyPostOut, OkOut, PostCreateIn, PostUpdateIn, ReactionIn, SolveIn

router = APIRouter(prefix="/posts", tags=["posts"])


@router.post(
    "",
    response_model=AnyPostOut,
    status_code=201,
    dependencies=[
        Depends(rate_limit("post_create", 5, 3600, "user")),
        Depends(rate_limit("post_create_day", 30, 86400, "user")),
    ],
)
async def create_post(data: PostCreateIn, user: ActiveUser, db: DB) -> AnyPostOut:
    return await posts_service.create_post(db, user, data)


@router.get("/{post_id}", response_model=AnyPostOut)
async def get_post(post_id: uuid.UUID, viewer: OptionalUser, db: DB) -> AnyPostOut:
    return await posts_service.get_post(db, post_id, viewer)


@router.patch(
    "/{post_id}",
    response_model=AnyPostOut,
    dependencies=[Depends(rate_limit("post_update", 30, 3600, "user"))],
)
async def update_post(
    post_id: uuid.UUID, data: PostUpdateIn, user: ActiveUser, db: DB
) -> AnyPostOut:
    return await posts_service.update_post(db, user, post_id, data)


@router.delete("/{post_id}", response_model=OkOut)
async def delete_post(post_id: uuid.UUID, user: ActiveUser, db: DB) -> OkOut:
    await posts_service.delete_post(db, user, post_id)
    return OkOut()


@router.put(
    "/{post_id}/reaction",
    response_model=AnyPostOut,
    dependencies=[Depends(rate_limit("reaction", 120, 3600, "user"))],
)
async def react(post_id: uuid.UUID, data: ReactionIn, user: ActiveUser, db: DB) -> AnyPostOut:
    return await posts_service.react(db, user, post_id, data.kind)


@router.delete(
    "/{post_id}/reaction",
    response_model=AnyPostOut,
    dependencies=[Depends(rate_limit("reaction", 120, 3600, "user"))],
)
async def unreact(post_id: uuid.UUID, user: ActiveUser, db: DB) -> AnyPostOut:
    return await posts_service.unreact(db, user, post_id)


@router.post(
    "/{post_id}/solve",
    response_model=AnyPostOut,
    dependencies=[Depends(rate_limit("solve", 30, 3600, "user"))],
)
async def solve(post_id: uuid.UUID, data: SolveIn, user: ActiveUser, db: DB) -> AnyPostOut:
    return await posts_service.solve(db, user, post_id, data.comment_id)


@router.delete(
    "/{post_id}/solve",
    response_model=AnyPostOut,
    dependencies=[Depends(rate_limit("solve", 30, 3600, "user"))],
)
async def unsolve(post_id: uuid.UUID, user: ActiveUser, db: DB) -> AnyPostOut:
    return await posts_service.unsolve(db, user, post_id)
