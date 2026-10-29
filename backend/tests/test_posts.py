import uuid
from datetime import timedelta

import httpx
from sqlalchemy import select, update

from database import SessionLocal
from models import Post, Tag, UserStatus
from tests.conftest import RANT, create_rant, make_user
from utils import utcnow


async def test_create_and_get_rant(client: httpx.AsyncClient):
    user, headers = await make_user("ranter")
    post = await create_rant(client, headers)
    assert post["is_anonymous"] is False
    assert post["author"]["handle"] == "ranter"
    assert post["moderation_state"] == "published"
    assert post["tags"] == ["meetings", "corporate"]
    assert post["is_own"] and post["can_edit"]
    public = (await client.get(f"/api/v1/posts/{post['id']}")).json()
    assert public["is_own"] is False and public["my_reaction"] is None


async def test_validation_and_sanitisation(client: httpx.AsyncClient):
    _, headers = await make_user("val")
    r = await client.post("/api/v1/posts", headers=headers, json={**RANT, "frustration_level": 9})
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/posts", headers=headers, json={**RANT, "tags": ["ok", "Bad Tag!"]}
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/posts", headers=headers, json={**RANT, "tags": [f"t{i}x" for i in range(6)]}
    )
    assert r.status_code == 422
    post = await create_rant(
        client,
        headers,
        title="  <b>Hello</b>   world  ",
        body="<script>alert(1)</script>hi‮ there\n\n\n\nend",
        tags=["#Burn Out", "burn-out"],
    )
    assert post["title"] == "Hello world"
    assert "<script>" not in post["body"] and "‮" not in post["body"]
    assert "\n\n\n" not in post["body"]
    assert post["tags"] == ["burn-out"]


async def test_auth_required_and_onboarding_and_suspension(client: httpx.AsyncClient):
    assert (await client.post("/api/v1/posts", json=RANT)).status_code == 401
    _, headers = await make_user("newbie", onboarded=False)
    r = await client.post("/api/v1/posts", json=RANT, headers=headers)
    assert r.status_code == 403 and r.json()["error"]["code"] == "onboarding_required"
    _, headers = await make_user(
        "suspended", status=UserStatus.suspended, suspended_until=utcnow() + timedelta(days=1)
    )
    r = await client.post("/api/v1/posts", json=RANT, headers=headers)
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_suspended"


async def test_edit_window_and_ownership(client: httpx.AsyncClient):
    _, headers = await make_user("editor")
    _, other = await make_user("other")
    post = await create_rant(client, headers)
    r = await client.patch(
        f"/api/v1/posts/{post['id']}",
        headers=headers,
        json={"title": "Edited title here", "tags": ["new-tag"]},
    )
    assert r.status_code == 200 and r.json()["title"] == "Edited title here"
    assert r.json()["edited_at"] is not None
    assert (
        await client.patch(f"/api/v1/posts/{post['id']}", headers=other, json={"title": "hijack"})
    ).status_code == 403
    async with SessionLocal() as db:
        await db.execute(update(Post).values(created_at=utcnow() - timedelta(minutes=20)))
        await db.commit()
    r = await client.patch(f"/api/v1/posts/{post['id']}", headers=headers, json={"body": "late"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "edit_window_closed"
    r = await client.patch(
        f"/api/v1/posts/{post['id']}", headers=headers, json={"status": "seeking_advice"}
    )
    assert r.status_code == 200 and r.json()["status"] == "seeking_advice"
    async with SessionLocal() as db:
        tags = {t.name: t.post_count for t in (await db.scalars(select(Tag))).all()}
    assert tags == {"meetings": 0, "corporate": 0, "new-tag": 1}


async def test_delete_rant(client: httpx.AsyncClient):
    _, headers = await make_user("deleter")
    _, other = await make_user("nosy")
    post = await create_rant(client, headers)
    assert (await client.delete(f"/api/v1/posts/{post['id']}", headers=other)).status_code == 403
    assert (await client.delete(f"/api/v1/posts/{post['id']}", headers=headers)).status_code == 200
    assert (await client.get(f"/api/v1/posts/{post['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/posts/{uuid.uuid4()}")).status_code == 404


async def test_reactions_count_and_switch(client: httpx.AsyncClient):
    _, author = await make_user("author")
    _, a = await make_user("reactor_a")
    _, b = await make_user("reactor_b")
    post = await create_rant(client, author)
    url = f"/api/v1/posts/{post['id']}/reaction"
    r = await client.put(url, headers=a, json={"kind": "same"})
    assert r.json()["reactions"] == {"same": 1, "hug": 0, "rage": 0, "lol": 0, "total": 1}
    assert r.json()["my_reaction"] == "same"
    await client.put(url, headers=a, json={"kind": "same"})  # idempotent
    await client.put(url, headers=b, json={"kind": "rage"})
    r = await client.put(url, headers=a, json={"kind": "hug"})  # switch
    assert r.json()["reactions"] == {"same": 0, "hug": 1, "rage": 1, "lol": 0, "total": 2}
    r = await client.delete(url, headers=a)
    assert r.json()["reactions"]["total"] == 1 and r.json()["my_reaction"] is None
    r = await client.delete(url, headers=a)  # idempotent
    assert r.json()["reactions"]["total"] == 1
    assert (await client.put(url, headers=a, json={"kind": "angry"})).status_code == 422
    notifs = (await client.get("/api/v1/notifications", headers=author)).json()["items"]
    assert {n["type"] for n in notifs} == {"reaction"} and len(notifs) == 2


async def test_concurrent_reactions_keep_counts_consistent(client: httpx.AsyncClient):
    import asyncio

    _, author = await make_user("hot")
    users = [await make_user(f"fan_{i}") for i in range(8)]
    post = await create_rant(client, author)
    url = f"/api/v1/posts/{post['id']}/reaction"
    await asyncio.gather(*(client.put(url, headers=h, json={"kind": "rage"}) for _, h in users))
    await asyncio.gather(*(client.put(url, headers=h, json={"kind": "rage"}) for _, h in users))
    r = await client.get(f"/api/v1/posts/{post['id']}")
    assert r.json()["reactions"]["rage"] == 8


async def test_solve_with_pinned_comment_awards_helper_score(client: httpx.AsyncClient):
    _, author = await make_user("stuck")
    helper, helper_h = await make_user("helper")
    post = await create_rant(client, author)
    comment = (
        await client.post(
            f"/api/v1/posts/{post['id']}/comments",
            headers=helper_h,
            json={"body": "Decline meetings without agendas.", "flair": "advice"},
        )
    ).json()
    assert (
        await client.post(
            f"/api/v1/posts/{post['id']}/solve",
            headers=helper_h,
            json={"comment_id": comment["id"]},
        )
    ).status_code == 403
    r = await client.post(
        f"/api/v1/posts/{post['id']}/solve", headers=author, json={"comment_id": comment["id"]}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "solved" and r.json()["pinned_comment_id"] == comment["id"]
    profile = (await client.get("/api/v1/users/helper")).json()
    assert profile["helper_score"] == 10
    solved_feed = (await client.get("/api/v1/feed", params={"sort": "solved"})).json()
    assert [p["id"] for p in solved_feed["items"]] == [post["id"]]
    r = await client.delete(f"/api/v1/posts/{post['id']}/solve", headers=author)
    assert r.json()["status"] == "open" and r.json()["pinned_comment_id"] is None
    assert (await client.get("/api/v1/users/helper")).json()["helper_score"] == 0
    types = [
        n["type"]
        for n in (await client.get("/api/v1/notifications", headers=helper_h)).json()["items"]
    ]
    assert "solved" in types


async def test_badges_awarded(client: httpx.AsyncClient):
    _, author = await make_user("survivor")
    for i in range(5):
        post = await create_rant(client, author, title=f"Problem number {i}")
        await client.post(f"/api/v1/posts/{post['id']}/solve", headers=author, json={})
    profile = (await client.get("/api/v1/users/survivor")).json()
    assert profile["badges"] == ["survivor"] and profile["solved_count"] == 5


async def test_default_anonymous_setting(client: httpx.AsyncClient):
    _, headers = await make_user("shy")
    settings = (await client.get("/api/v1/me/settings", headers=headers)).json()
    settings["privacy"]["default_anonymous"] = True
    assert (
        await client.patch(
            "/api/v1/me/settings", headers=headers, json={"privacy": settings["privacy"]}
        )
    ).status_code == 200
    post = await create_rant(client, headers)
    assert post["is_anonymous"] is True and "author" not in post
    post = await create_rant(client, headers, is_anonymous=False)
    assert post["is_anonymous"] is False
