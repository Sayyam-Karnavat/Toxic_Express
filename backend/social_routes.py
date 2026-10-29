"""Follow / block / mute users, follow topics, list followers."""

import uuid

from fastapi import APIRouter, Depends, Query

import social_service
from deps import DB, ActiveUser, CurrentUser, OptionalUser, rate_limit
from schemas import OkOut, TopicIn, TopicsOut, UserPage, UserSummary

router = APIRouter(tags=["social"])

SocialLimit = Depends(rate_limit("social", 120, 3600, "user"))


@router.post("/users/{handle}/follow", response_model=OkOut, dependencies=[SocialLimit])
async def follow(handle: str, user: ActiveUser, db: DB) -> OkOut:
    await social_service.follow(db, user, handle)
    return OkOut()


@router.delete("/users/{handle}/follow", response_model=OkOut, dependencies=[SocialLimit])
async def unfollow(handle: str, user: CurrentUser, db: DB) -> OkOut:
    await social_service.unfollow(db, user, handle)
    return OkOut()


@router.post("/users/{handle}/block", response_model=OkOut, dependencies=[SocialLimit])
async def block(handle: str, user: CurrentUser, db: DB) -> OkOut:
    await social_service.block(db, user, handle)
    return OkOut()


@router.delete("/me/blocks/{user_id}", response_model=OkOut, dependencies=[SocialLimit])
async def unblock(user_id: uuid.UUID, user: CurrentUser, db: DB) -> OkOut:
    await social_service.unblock(db, user, user_id)
    return OkOut()


@router.post("/users/{handle}/mute", response_model=OkOut, dependencies=[SocialLimit])
async def mute(handle: str, user: CurrentUser, db: DB) -> OkOut:
    await social_service.mute(db, user, handle)
    return OkOut()


@router.delete("/me/mutes/{user_id}", response_model=OkOut, dependencies=[SocialLimit])
async def unmute(user_id: uuid.UUID, user: CurrentUser, db: DB) -> OkOut:
    await social_service.unmute(db, user, user_id)
    return OkOut()


@router.get("/me/blocks", response_model=list[UserSummary])
async def blocks(user: CurrentUser, db: DB) -> list[UserSummary]:
    return await social_service.list_blocked_or_muted(db, user, "blocks")


@router.get("/me/mutes", response_model=list[UserSummary])
async def mutes(user: CurrentUser, db: DB) -> list[UserSummary]:
    return await social_service.list_blocked_or_muted(db, user, "mutes")


Cursor = Query(None, max_length=200)


@router.get("/users/{handle}/followers", response_model=UserPage)
async def followers(
    handle: str, viewer: OptionalUser, db: DB, cursor: str | None = Cursor
) -> UserPage:
    return await social_service.list_follows(db, handle, viewer, "followers", cursor)


@router.get("/users/{handle}/following", response_model=UserPage)
async def following(
    handle: str, viewer: OptionalUser, db: DB, cursor: str | None = Cursor
) -> UserPage:
    return await social_service.list_follows(db, handle, viewer, "following", cursor)


@router.get("/me/topics", response_model=TopicsOut)
async def topics(user: CurrentUser, db: DB) -> TopicsOut:
    return TopicsOut(topics=await social_service.list_topics(db, user))


@router.post("/me/topics", response_model=TopicsOut, dependencies=[SocialLimit])
async def follow_topic(data: TopicIn, user: CurrentUser, db: DB) -> TopicsOut:
    await social_service.follow_topic(db, user, data.topic)
    return TopicsOut(topics=await social_service.list_topics(db, user))


@router.delete("/me/topics/{topic}", response_model=TopicsOut, dependencies=[SocialLimit])
async def unfollow_topic(topic: str, user: CurrentUser, db: DB) -> TopicsOut:
    await social_service.unfollow_topic(db, user, topic)
    return TopicsOut(topics=await social_service.list_topics(db, user))
