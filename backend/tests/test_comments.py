from datetime import timedelta

import httpx
from sqlalchemy import update

from database import SessionLocal
from models import Comment
from tests.conftest import create_rant, make_user
from utils import utcnow


async def _comment(client, headers, post_id, body="Been there.", **extra):
    r = await client.post(
        f"/api/v1/posts/{post_id}/comments", headers=headers, json={"body": body, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_threads_are_two_levels_and_counted(client: httpx.AsyncClient):
    _, author = await make_user("op_user")
    _, a = await make_user("alice")
    _, b = await make_user("bob")
    post = await create_rant(client, author)
    top = await _comment(client, a, post["id"], "Top level", flair="advice")
    reply = await _comment(client, b, post["id"], "Reply", parent_id=top["id"])
    nested = await _comment(client, a, post["id"], "Reply to reply", parent_id=reply["id"])
    assert nested["parent_id"] == top["id"]  # flattened under the top-level comment
    page = (await client.get(f"/api/v1/posts/{post['id']}/comments")).json()
    assert len(page["items"]) == 1
    assert page["items"][0]["reply_count"] == 2
    assert [r["body"] for r in page["items"][0]["replies"]] == ["Reply", "Reply to reply"]
    assert (await client.get(f"/api/v1/posts/{post['id']}")).json()["comment_count"] == 3
    types = sorted(
        n["type"] for n in (await client.get("/api/v1/notifications", headers=a)).json()["items"]
    )
    assert types == ["reply"]  # alice gets a reply notification from bob, not from herself


async def test_comment_pagination(client: httpx.AsyncClient):
    _, author = await make_user("popular")
    _, fan = await make_user("fan")
    post = await create_rant(client, author)
    for i in range(25):
        await _comment(client, fan, post["id"], f"comment {i}")
    first = (await client.get(f"/api/v1/posts/{post['id']}/comments")).json()
    second = (
        await client.get(
            f"/api/v1/posts/{post['id']}/comments", params={"cursor": first["next_cursor"]}
        )
    ).json()
    bodies = [c["body"] for c in first["items"] + second["items"]]
    assert bodies == [f"comment {i}" for i in range(25)] and second["next_cursor"] is None
    bad = await client.get(f"/api/v1/posts/{post['id']}/comments", params={"cursor": "garbage!"})
    assert bad.status_code == 400


async def test_edit_delete_and_placeholder(client: httpx.AsyncClient):
    _, author = await make_user("writer")
    _, other = await make_user("replier")
    post = await create_rant(client, author)
    c = await _comment(client, author, post["id"], "original")
    await _comment(client, other, post["id"], "a reply", parent_id=c["id"])
    r = await client.patch(f"/api/v1/comments/{c['id']}", headers=author, json={"body": "edited"})
    assert r.json()["body"] == "edited" and r.json()["edited_at"]
    assert (
        await client.patch(f"/api/v1/comments/{c['id']}", headers=other, json={"body": "x"})
    ).status_code == 403
    assert (await client.delete(f"/api/v1/comments/{c['id']}", headers=author)).status_code == 200
    page = (await client.get(f"/api/v1/posts/{post['id']}/comments")).json()
    assert page["items"][0]["deleted"] is True and page["items"][0]["body"] == "[deleted]"
    assert page["items"][0]["author"] is None
    assert (await client.get(f"/api/v1/posts/{post['id']}")).json()["comment_count"] == 1
    async with SessionLocal() as db:
        await db.execute(update(Comment).values(created_at=utcnow() - timedelta(hours=1)))
        await db.commit()
    late = await client.patch(
        f"/api/v1/comments/{page['items'][0]['replies'][0]['id']}",
        headers=other,
        json={"body": "late edit"},
    )
    assert late.status_code == 403


async def test_helpful_votes(client: httpx.AsyncClient):
    _, author = await make_user("asker")
    helper, helper_h = await make_user("wise")
    _, voter = await make_user("voter")
    post = await create_rant(client, author)
    c = await _comment(client, helper_h, post["id"], "Try this", flair="advice")
    url = f"/api/v1/comments/{c['id']}/helpful"
    assert (await client.put(url, headers=helper_h)).status_code == 400  # own comment
    r = await client.put(url, headers=voter)
    assert r.json()["helpful_count"] == 1 and r.json()["my_helpful"] is True
    await client.put(url, headers=voter)  # idempotent
    await client.put(url, headers=author)
    assert (await client.get("/api/v1/users/wise")).json()["helper_score"] == 2
    r = await client.delete(url, headers=voter)
    assert r.json()["helpful_count"] == 1
    assert (await client.get("/api/v1/users/wise")).json()["helper_score"] == 1


async def test_who_can_comment_and_blocks(client: httpx.AsyncClient):
    _, author = await make_user("private_person")
    _, stranger = await make_user("stranger")
    _, friend = await make_user("friend")
    await client.post("/api/v1/users/private_person/follow", headers=friend)
    s = (await client.get("/api/v1/me/settings", headers=author)).json()
    s["privacy"]["who_can_comment"] = "followers"
    await client.patch("/api/v1/me/settings", headers=author, json={"privacy": s["privacy"]})
    post = await create_rant(client, author)
    r = await client.post(
        f"/api/v1/posts/{post['id']}/comments", headers=stranger, json={"body": "hi"}
    )
    assert r.status_code == 403
    await _comment(client, friend, post["id"], "hello friend")
    await _comment(client, author, post["id"], "author can always comment")
    await client.post("/api/v1/users/friend/block", headers=author)
    r = await client.post(
        f"/api/v1/posts/{post['id']}/comments", headers=friend, json={"body": "still here?"}
    )
    assert r.status_code in (403, 404)
    page = (await client.get(f"/api/v1/posts/{post['id']}/comments", headers=author)).json()
    assert [c["body"] for c in page["items"]] == ["author can always comment"]


async def test_comment_on_unpublished_or_missing_post(client: httpx.AsyncClient):
    import uuid

    _, user = await make_user("lost")
    r = await client.post(
        f"/api/v1/posts/{uuid.uuid4()}/comments", headers=user, json={"body": "?"}
    )
    assert r.status_code == 404
