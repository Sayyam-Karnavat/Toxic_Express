import httpx

from feed import compute_trending
from tests.conftest import create_rant, make_user, reset_rate_limits


async def test_latest_feed_pagination_and_filters(client: httpx.AsyncClient):
    _, a = await make_user("writer_a")
    for i in range(23):
        await reset_rate_limits()
        await create_rant(
            client,
            a,
            title=f"Rant number {i:02d}",
            category="tech" if i % 2 else "money",
            tags=["even"] if i % 2 == 0 else [],
        )
    first = (await client.get("/api/v1/feed")).json()
    second = (await client.get("/api/v1/feed", params={"cursor": first["next_cursor"]})).json()
    titles = [p["title"] for p in first["items"] + second["items"]]
    assert titles == [f"Rant number {i:02d}" for i in reversed(range(23))]
    assert second["next_cursor"] is None
    tech = (await client.get("/api/v1/feed", params={"category": "tech"})).json()["items"]
    assert len(tech) == 11 and {p["category"] for p in tech} == {"tech"}
    tagged = (await client.get("/api/v1/feed", params={"tag": "even"})).json()["items"]
    assert len(tagged) == 12
    assert (await client.get("/api/v1/feed", params={"category": "nope"})).status_code == 422


async def test_muted_words_categories_and_users(client: httpx.AsyncClient):
    _, a = await make_user("noisy")
    _, b = await make_user("calm")
    _, viewer = await make_user("picky")
    await create_rant(client, a, title="Crypto crashed again", category="money")
    await create_rant(client, b, title="Printer on fire", category="tech")
    await create_rant(
        client, b, title="Train late 100% again", category="commute", content_warning=True
    )
    s = (await client.get("/api/v1/me/settings", headers=viewer)).json()
    s["content"].update(muted_words=["printer"], hide_content_warning_posts=True)
    await client.patch("/api/v1/me/settings", headers=viewer, json={"content": s["content"]})
    titles = [
        p["title"] for p in (await client.get("/api/v1/feed", headers=viewer)).json()["items"]
    ]
    assert titles == ["Crypto crashed again"]
    await client.post("/api/v1/users/noisy/mute", headers=viewer)
    assert (await client.get("/api/v1/feed", headers=viewer)).json()["items"] == []
    s["content"].update(muted_words=["100%"], hide_content_warning_posts=False)
    await client.patch("/api/v1/me/settings", headers=viewer, json={"content": s["content"]})
    titles = [
        p["title"] for p in (await client.get("/api/v1/feed", headers=viewer)).json()["items"]
    ]
    assert titles == ["Printer on fire"]  # "%" in a muted word is matched literally


async def test_follow_unfollow_counts_and_lists(client: httpx.AsyncClient):
    _, a = await make_user("alpha")
    _, b = await make_user("beta")
    assert (await client.post("/api/v1/users/beta/follow", headers=a)).status_code == 200
    await client.post("/api/v1/users/beta/follow", headers=a)  # idempotent
    assert (await client.post("/api/v1/users/alpha/follow", headers=a)).status_code == 400
    beta = (await client.get("/api/v1/users/beta", headers=a)).json()
    assert beta["follower_count"] == 1 and beta["is_following"] is True
    followers = (await client.get("/api/v1/users/beta/followers")).json()
    assert [u["handle"] for u in followers["items"]] == ["alpha"]
    following = (await client.get("/api/v1/users/alpha/following")).json()
    assert [u["handle"] for u in following["items"]] == ["beta"]
    await client.delete("/api/v1/users/beta/follow", headers=a)
    assert (await client.get("/api/v1/users/beta")).json()["follower_count"] == 0


async def test_block_hides_both_ways_and_removes_follows(client: httpx.AsyncClient):
    _, a = await make_user("blocker")
    blocked, b = await make_user("blockee")
    await client.post("/api/v1/users/blockee/follow", headers=a)
    await client.post("/api/v1/users/blocker/follow", headers=b)
    post_b = await create_rant(client, b, title="Blockee rant here")
    post_a = await create_rant(client, a, title="Blocker rant here")
    assert (await client.post("/api/v1/users/blockee/block", headers=a)).status_code == 200
    assert (await client.get("/api/v1/users/blockee", headers=a)).json()["follower_count"] == 0
    assert (await client.get("/api/v1/users/blocker", headers=b)).status_code == 404
    assert (await client.get(f"/api/v1/posts/{post_a['id']}", headers=b)).status_code == 404
    assert (await client.get(f"/api/v1/posts/{post_b['id']}", headers=a)).status_code == 404
    feed_a = [p["id"] for p in (await client.get("/api/v1/feed", headers=a)).json()["items"]]
    assert post_b["id"] not in feed_a
    r = await client.put(f"/api/v1/posts/{post_a['id']}/reaction", headers=b, json={"kind": "lol"})
    assert r.status_code == 404
    assert (await client.post("/api/v1/users/blocker/follow", headers=b)).status_code == 404
    blocks = (await client.get("/api/v1/me/blocks", headers=a)).json()
    assert [u["handle"] for u in blocks] == ["blockee"]
    await client.delete(f"/api/v1/me/blocks/{blocked.id}", headers=a)
    assert (await client.get(f"/api/v1/posts/{post_a['id']}", headers=b)).status_code == 200


async def test_following_feed_with_topics(client: httpx.AsyncClient):
    _, a = await make_user("followed")
    _, b = await make_user("random")
    _, me = await make_user("me_user")
    await client.post("/api/v1/users/followed/follow", headers=me)
    p1 = await create_rant(client, a, title="From someone I follow", category="life")
    p2 = await create_rant(client, b, title="Random health rant", category="health")
    p3 = await create_rant(client, b, title="Random tagged rant", category="life", tags=["burnout"])
    await create_rant(client, b, title="Unrelated rant", category="life")
    mine = await create_rant(client, me, title="My own rant", category="money")
    await client.post("/api/v1/me/topics", headers=me, json={"topic": "category:health"})
    r = await client.post("/api/v1/me/topics", headers=me, json={"topic": "tag:burnout"})
    assert r.json()["topics"] == ["category:health", "tag:burnout"]
    assert (
        await client.post("/api/v1/me/topics", headers=me, json={"topic": "bogus"})
    ).status_code == 422
    ids = {
        p["id"] for p in (await client.get("/api/v1/feed/following", headers=me)).json()["items"]
    }
    assert ids == {p1["id"], p2["id"], p3["id"], mine["id"]}


async def test_trending_ranks_engagement(client: httpx.AsyncClient):
    _, a = await make_user("trend_a")
    fans = [await make_user(f"trend_fan_{i}") for i in range(5)]
    quiet = await create_rant(client, a, title="Quiet rant nobody saw")
    loud = await create_rant(client, a, title="Loud rant everybody loved")
    for _, h in fans:
        await client.put(f"/api/v1/posts/{loud['id']}/reaction", headers=h, json={"kind": "same"})
    await compute_trending()
    items = (await client.get("/api/v1/feed", params={"sort": "trending"})).json()["items"]
    assert [p["id"] for p in items][:2] == [loud["id"], quiet["id"]]
    work = (
        await client.get("/api/v1/feed", params={"sort": "trending", "category": "work"})
    ).json()
    assert len(work["items"]) == 2


async def test_search_posts_users_tags(client: httpx.AsyncClient):
    _, a = await make_user("searchable_sue", display_name="Sue Searchable")
    _, hidden = await make_user("hidden_hank")
    await create_rant(
        client,
        a,
        title="Landlord ignores the broken heating",
        body="It is freezing and the landlord keeps ignoring me",
        tags=["landlord"],
    )
    await create_rant(client, a, title="Unrelated", body="Nothing to see")
    s = (await client.get("/api/v1/me/settings", headers=hidden)).json()
    s["privacy"]["searchable"] = False
    await client.patch("/api/v1/me/settings", headers=hidden, json={"privacy": s["privacy"]})
    r = (await client.get("/api/v1/search", params={"q": "landlord heating"})).json()
    assert [p["title"] for p in r["posts"]] == ["Landlord ignores the broken heating"]
    assert [t["name"] for t in r["tags"]] == ["landlord"]
    users = (await client.get("/api/v1/search", params={"q": "sue", "type": "users"})).json()[
        "users"
    ]
    assert [u["handle"] for u in users] == ["searchable_sue"]
    nobody = (await client.get("/api/v1/search", params={"q": "hank", "type": "users"})).json()
    assert nobody["users"] == []
    weird = await client.get("/api/v1/search", params={"q": "' OR 1=1 -- %_\\"})
    assert weird.status_code == 200


async def test_profile_and_settings(client: httpx.AsyncClient):
    _, h = await make_user("profiled")
    r = await client.patch(
        "/api/v1/me",
        headers=h,
        json={
            "headline": "Backend dev fighting legacy code",
            "bio": "I rant so you don't have to",
            "profession": "Engineer",
            "location": "Pune",
            "frustrated_status": "Flaky CI",
            "links": ["https://example.com/me"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["links"] == ["https://example.com/me"]
    s = (await client.get("/api/v1/me/settings", headers=h)).json()
    s["privacy"].update(hide_profession=True, hide_location=True)
    await client.patch("/api/v1/me/settings", headers=h, json={"privacy": s["privacy"]})
    public = (await client.get("/api/v1/users/profiled")).json()
    assert public["profession"] is None and public["location"] is None
    own = (await client.get("/api/v1/users/profiled", headers=h)).json()
    assert own["profession"] == "Engineer" and own["is_me"] is True
    bad = await client.patch("/api/v1/me", headers=h, json={"links": ["javascript:alert(1)"]})
    assert bad.status_code == 422
    r = await client.patch("/api/v1/me", headers=h, json={"handle": "profiled_v2"})
    assert r.json()["handle"] == "profiled_v2"
    r = await client.patch("/api/v1/me", headers=h, json={"handle": "profiled_v3"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "handle_cooldown"
    export = (await client.get("/api/v1/me/export", headers=h)).json()
    assert export["profile"]["handle"] == "profiled_v2"


async def test_notifications_read_flow(client: httpx.AsyncClient):
    _, a = await make_user("notified")
    _, b = await make_user("notifier")
    await client.post("/api/v1/users/notified/follow", headers=b)
    post = await create_rant(client, a)
    await client.put(f"/api/v1/posts/{post['id']}/reaction", headers=b, json={"kind": "hug"})
    assert (await client.get("/api/v1/notifications/unread-count", headers=a)).json() == {
        "unread": 2
    }
    items = (await client.get("/api/v1/notifications", headers=a)).json()["items"]
    assert items[0]["actor"]["handle"] == "notifier"
    await client.post("/api/v1/notifications/read", headers=a, json={"ids": [items[0]["id"]]})
    assert (await client.get("/api/v1/notifications/unread-count", headers=a)).json() == {
        "unread": 1
    }
    await client.post("/api/v1/notifications/read", headers=a, json={"all": True})
    assert (await client.get("/api/v1/notifications/unread-count", headers=a)).json() == {
        "unread": 0
    }
    s = (await client.get("/api/v1/me/settings", headers=a)).json()
    s["notifications"]["reactions"] = False
    await client.patch("/api/v1/me/settings", headers=a, json={"notifications": s["notifications"]})
    _, c = await make_user("third")
    await client.put(f"/api/v1/posts/{post['id']}/reaction", headers=c, json={"kind": "lol"})
    assert (await client.get("/api/v1/notifications/unread-count", headers=a)).json() == {
        "unread": 0
    }


async def test_meta(client: httpx.AsyncClient):
    r = await client.get("/api/v1/meta")
    assert r.status_code == 200 and len(r.json()["categories"]) == 8
    assert r.headers["cache-control"] == "public, max-age=3600"
