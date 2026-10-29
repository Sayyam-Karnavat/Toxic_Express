import httpx
import pytest
import respx
from pydantic import SecretStr

import moderation
from config import settings
from models import Role
from tests.conftest import RANT, create_rant, make_user
from worker import cron_sweep_pending_moderation

ZERO = {
    k: 0.001
    for k in [
        "harassment",
        "harassment/threatening",
        "hate",
        "hate/threatening",
        "illicit",
        "illicit/violent",
        "self-harm",
        "self-harm/intent",
        "self-harm/instructions",
        "sexual",
        "sexual/minors",
        "violence",
        "violence/graphic",
    ]
}


def _scores(**overrides: float) -> dict:
    scores = dict(ZERO)
    scores.update(
        {
            k.replace("__", "/").replace("_", "-")
            if k.startswith("self")
            else k.replace("__", "/"): v
            for k, v in overrides.items()
        }
    )
    return {
        "results": [{"flagged": any(v > 0.5 for v in scores.values()), "category_scores": scores}]
    }


@pytest.fixture
def openai_on(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("sk-test"))
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="test").pass_through()
        yield mock.post(moderation.OPENAI_MODERATION_URL)


async def test_personal_info_is_rejected_with_guidance(client: httpx.AsyncClient):
    _, h = await make_user("doxxer")
    r = await client.post(
        "/api/v1/posts",
        headers=h,
        json={**RANT, "body": "My ex's number is +1 (415) 555-0134, call him"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "content_rejected"
    assert "phone number" in r.json()["error"]["message"]


async def test_threats_rejected(client: httpx.AsyncClient, openai_on):
    openai_on.respond(200, json=_scores(harassment__threatening=0.95))
    _, h = await make_user("threat")
    r = await client.post("/api/v1/posts", headers=h, json=RANT)
    assert (
        r.status_code == 422 and "harassment/threatening" in r.json()["error"]["details"]["reasons"]
    )


async def test_venting_with_swearing_is_published(client: httpx.AsyncClient, openai_on):
    openai_on.respond(200, json=_scores(harassment=0.4, violence=0.3))
    _, h = await make_user("swearer")
    post = await create_rant(client, h, body="This f***ing printer is the worst thing ever made")
    assert post["moderation_state"] == "published" and post["show_crisis_resources"] is False


async def test_hate_goes_to_review_and_is_hidden(client: httpx.AsyncClient, openai_on):
    openai_on.respond(200, json=_scores(hate=0.8))
    _, h = await make_user("borderline")
    _, other = await make_user("reader")
    post = await create_rant(client, h)
    assert post["moderation_state"] == "in_review"
    assert (await client.get(f"/api/v1/posts/{post['id']}", headers=other)).status_code == 404
    assert (await client.get("/api/v1/feed")).json()["items"] == []
    assert (await client.get(f"/api/v1/posts/{post['id']}", headers=h)).status_code == 200


async def test_self_harm_published_with_crisis_resources(client: httpx.AsyncClient, openai_on):
    openai_on.respond(200, json=_scores(self_harm=0.8))
    _, h = await make_user("struggling")
    post = await create_rant(client, h, body="I don't see the point anymore")
    assert post["moderation_state"] == "published"
    assert post["show_crisis_resources"] is True


async def test_transient_moderation_errors_are_retried(client: httpx.AsyncClient, openai_on):
    openai_on.side_effect = [httpx.Response(429), httpx.Response(200, json=_scores())]
    _, h = await make_user("retry")
    post = await create_rant(client, h)
    assert post["moderation_state"] == "published" and openai_on.call_count == 2


async def test_moderation_outage_holds_content_then_sweeps(client: httpx.AsyncClient, openai_on):
    openai_on.respond(503)
    _, h = await make_user("outage")
    post = await create_rant(client, h)
    assert post["moderation_state"] == "pending"  # fail-safe: never auto-publish unchecked
    assert (await client.get("/api/v1/feed")).json()["items"] == []
    openai_on.respond(200, json=_scores())
    from datetime import timedelta

    from sqlalchemy import update

    from database import SessionLocal
    from models import Post
    from utils import utcnow

    async with SessionLocal() as db:
        await db.execute(update(Post).values(updated_at=utcnow() - timedelta(minutes=5)))
        await db.commit()
    await cron_sweep_pending_moderation({})
    assert (await client.get(f"/api/v1/posts/{post['id']}")).json()[
        "moderation_state"
    ] == "published"


async def test_comment_moderation(client: httpx.AsyncClient, openai_on):
    openai_on.respond(200, json=_scores())
    _, author = await make_user("poster")
    _, troll = await make_user("troll")
    post = await create_rant(client, author)
    openai_on.respond(200, json=_scores(hate__threatening=0.9))
    r = await client.post(f"/api/v1/posts/{post['id']}/comments", headers=troll, json={"body": "x"})
    assert r.status_code == 422


# --- Reports & moderator tools -----------------------------------------------------------------


async def _report(client, headers, entity_type, entity_id, reason="harassment"):
    return await client.post(
        "/api/v1/reports",
        headers=headers,
        json={"entity_type": entity_type, "entity_id": entity_id, "reason": reason},
    )


async def test_reports_auto_hide_and_mod_review(client: httpx.AsyncClient):
    author, h = await make_user("reported", display_name="Reported Person")
    reporters = [await make_user(f"reporter_{i}") for i in range(3)]
    _, mod = await make_user("mod_mia", role=Role.mod)
    post = await create_rant(client, h, is_anonymous=True)
    assert (await _report(client, h, "post", post["id"])).status_code == 400  # own content
    for _, rh in reporters[:2]:
        assert (await _report(client, rh, "post", post["id"])).status_code == 201
    await _report(client, reporters[0][1], "post", post["id"])  # duplicate is idempotent
    assert (await client.get(f"/api/v1/posts/{post['id']}")).status_code == 200
    await _report(client, reporters[2][1], "post", post["id"])
    assert (await client.get(f"/api/v1/posts/{post['id']}")).status_code == 404  # auto-hidden

    assert (await client.get("/api/v1/admin/queue", headers=h)).status_code == 403
    queue = (await client.get("/api/v1/admin/queue", headers=mod)).json()["items"]
    assert len(queue) == 1 and queue[0]["report_count"] == 3
    assert queue[0]["is_anonymous"] is True
    assert queue[0]["author"]["handle"] == "reported"  # moderators can see who it really is

    r = await client.post(
        "/api/v1/admin/actions",
        headers=mod,
        json={"entity_type": "post", "entity_id": post["id"], "action": "approve"},
    )
    assert r.status_code == 201
    assert (await client.get(f"/api/v1/posts/{post['id']}")).status_code == 200
    assert (await client.get("/api/v1/admin/queue", headers=mod)).json()["items"] == []


async def test_remove_notify_and_appeal(client: httpx.AsyncClient):
    _, h = await make_user("appellant")
    _, mod = await make_user("mod_max", role=Role.mod)
    post = await create_rant(client, h, tags=["appeal-me"])
    action = (
        await client.post(
            "/api/v1/admin/actions",
            headers=mod,
            json={
                "entity_type": "post",
                "entity_id": post["id"],
                "action": "remove",
                "reason": "Targets a named person",
            },
        )
    ).json()
    assert (await client.get(f"/api/v1/posts/{post['id']}")).status_code == 404
    notes = (await client.get("/api/v1/notifications", headers=h)).json()["items"]
    assert notes[0]["type"] == "moderation" and notes[0]["data"]["action_id"] == action["id"]
    mine = (await client.get("/api/v1/me/moderation-actions", headers=h)).json()
    assert [a["id"] for a in mine] == [action["id"]]
    appeal = await client.post(
        "/api/v1/appeals",
        headers=h,
        json={
            "action_id": action["id"],
            "message": "It was about a fictional character, honestly.",
        },
    )
    assert appeal.status_code == 201
    dup = await client.post(
        "/api/v1/appeals",
        headers=h,
        json={"action_id": action["id"], "message": "Please look again at this one."},
    )
    assert dup.status_code == 409
    appeals = (await client.get("/api/v1/admin/appeals", headers=mod)).json()["items"]
    r = await client.post(
        f"/api/v1/admin/appeals/{appeals[0]['id']}/resolve",
        headers=mod,
        json={"accept": True, "note": "Fair point"},
    )
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert (await client.get(f"/api/v1/posts/{post['id']}")).status_code == 200
    audit = (await client.get("/api/v1/admin/audit", headers=mod)).json()["items"]
    assert [a["action"] for a in audit] == ["appeal_accepted", "remove"]


async def test_strikes_suspend_and_role_limits(client: httpx.AsyncClient):
    target, th = await make_user("repeat_offender")
    _, mod = await make_user("mod_lee", role=Role.mod)
    admin, admin_h = await make_user("admin_ada", role=Role.admin)
    for _ in range(3):
        r = await client.post(
            "/api/v1/admin/actions",
            headers=mod,
            json={
                "entity_type": "user",
                "entity_id": str(target.id),
                "action": "strike",
                "reason": "spam",
            },
        )
        assert r.status_code == 201
    me = (await client.get("/api/v1/me", headers=th)).json()
    assert me["status"] == "suspended" and me["suspended_until"]
    r = await client.post("/api/v1/posts", headers=th, json=RANT)
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_suspended"

    r = await client.post(
        "/api/v1/admin/actions",
        headers=mod,
        json={"entity_type": "user", "entity_id": str(target.id), "action": "ban"},
    )
    assert r.status_code == 403  # only admins ban
    r = await client.post(
        "/api/v1/admin/actions",
        headers=mod,
        json={"entity_type": "user", "entity_id": str(admin.id), "action": "suspend"},
    )
    assert r.status_code == 403  # mods cannot act on staff
    r = await client.post(
        "/api/v1/admin/actions",
        headers=admin_h,
        json={"entity_type": "user", "entity_id": str(target.id), "action": "ban"},
    )
    assert r.status_code == 201
    assert (await client.get("/api/v1/me", headers=th)).status_code == 401


async def test_self_harm_report_shows_resources(client: httpx.AsyncClient):
    _, h = await make_user("quiet")
    _, friend = await make_user("worried_friend")
    post = await create_rant(client, h)
    await _report(client, friend, "post", post["id"], reason="self_harm")
    assert (await client.get(f"/api/v1/posts/{post['id']}")).json()["show_crisis_resources"] is True


async def test_report_comment_and_user(client: httpx.AsyncClient):
    target, th = await make_user("commenter")
    _, rh = await make_user("reporter")
    _, mod = await make_user("mod_kim", role=Role.mod)
    post = await create_rant(client, rh)
    c = (
        await client.post(
            f"/api/v1/posts/{post['id']}/comments", headers=th, json={"body": "rude comment"}
        )
    ).json()
    assert (await _report(client, rh, "comment", c["id"])).status_code == 201
    assert (await _report(client, rh, "user", str(target.id), "spam")).status_code == 201
    types = {
        i["entity_type"]
        for i in (await client.get("/api/v1/admin/queue", headers=mod)).json()["items"]
    }
    assert types == {"comment", "user"}
    r = await client.post(
        "/api/v1/admin/actions",
        headers=mod,
        json={"entity_type": "comment", "entity_id": c["id"], "action": "remove"},
    )
    assert r.status_code == 201
    assert (await client.get(f"/api/v1/posts/{post['id']}")).json()["comment_count"] == 0


async def test_banned_and_deleting_users_content_is_hidden(client: httpx.AsyncClient):
    from tests.conftest import TEST_PASSWORD

    target, th = await make_user("soon_gone")
    _, other = await make_user("bystander")
    admin, admin_h = await make_user("admin_root", role=Role.admin)
    post = await create_rant(client, th)
    comment_post = await create_rant(client, other)
    await client.post(
        f"/api/v1/posts/{comment_post['id']}/comments", headers=th, json={"body": "my comment"}
    )

    r = await client.request(
        "DELETE", "/api/v1/me", headers=th, json={"password": TEST_PASSWORD, "confirm": "DELETE"}
    )
    assert r.status_code == 200
    assert (await client.get(f"/api/v1/posts/{post['id']}")).status_code == 404
    assert post["id"] not in (await client.get("/api/v1/feed")).text
    comments = (await client.get(f"/api/v1/posts/{comment_post['id']}/comments")).json()
    assert comments["items"] == []

    r = await client.post(
        "/api/v1/auth/login", json={"email": "soon_gone@example.com", "password": TEST_PASSWORD}
    )
    assert r.status_code == 200  # cancels deletion and restores content
    assert (await client.get(f"/api/v1/posts/{post['id']}")).status_code == 200

    await client.post(
        "/api/v1/admin/actions",
        headers=admin_h,
        json={"entity_type": "user", "entity_id": str(target.id), "action": "ban"},
    )
    assert (await client.get(f"/api/v1/posts/{post['id']}")).status_code == 404
    await client.post(
        "/api/v1/admin/actions",
        headers=admin_h,
        json={"entity_type": "user", "entity_id": str(target.id), "action": "unban"},
    )
    assert (await client.get(f"/api/v1/posts/{post['id']}")).status_code == 200
