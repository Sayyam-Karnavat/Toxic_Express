"""An anonymous rant must never expose its author through any endpoint."""

import httpx

from tests.conftest import create_rant, make_user


def _assert_no_identity(payload: object, *secrets: str) -> None:
    text = httpx.Response(200, json=payload).text
    for secret in secrets:
        assert secret not in text, f"leaked {secret!r} in {text[:300]}"


async def test_anonymous_post_never_leaks_author(client: httpx.AsyncClient):
    author, author_h = await make_user("secret_sam", display_name="Samantha Secret")
    viewer, viewer_h = await make_user("viewer")
    await client.post("/api/v1/users/secret_sam/follow", headers=viewer_h)
    await client.post("/api/v1/me/topics", headers=viewer_h, json={"topic": "category:work"})
    post = await create_rant(
        client,
        author_h,
        is_anonymous=True,
        title="Anonymous rant about my unbearable boss",
        body="Nobody can know this is me, unbearable situation",
    )
    secrets = (str(author.id), "secret_sam", "Samantha Secret", "secret_sam@example.com")
    pid = post["id"]

    # The OP replies on their own anonymous post: shown as OP, never as their profile.
    await client.put(f"/api/v1/posts/{pid}/reaction", headers=viewer_h, json={"kind": "hug"})
    viewer_comment = (
        await client.post(
            f"/api/v1/posts/{pid}/comments",
            headers=viewer_h,
            json={"body": "Hang in there", "flair": "support"},
        )
    ).json()
    op_reply = (
        await client.post(
            f"/api/v1/posts/{pid}/comments",
            headers=author_h,
            json={"body": "Thanks friend", "flair": "story", "parent_id": viewer_comment["id"]},
        )
    ).json()
    assert op_reply["is_anonymous"] is True and op_reply["is_op"] is True
    await client.post(
        f"/api/v1/posts/{pid}/solve", headers=author_h, json={"comment_id": viewer_comment["id"]}
    )

    responses = {
        "detail": await client.get(f"/api/v1/posts/{pid}", headers=viewer_h),
        "detail_public": await client.get(f"/api/v1/posts/{pid}"),
        "latest": await client.get("/api/v1/feed", headers=viewer_h),
        "trending": await client.get("/api/v1/feed", params={"sort": "trending"}),
        "solved": await client.get("/api/v1/feed", params={"sort": "solved"}),
        "category": await client.get("/api/v1/feed", params={"category": "work"}),
        "following": await client.get("/api/v1/feed/following", headers=viewer_h),
        "comments": await client.get(f"/api/v1/posts/{pid}/comments", headers=viewer_h),
        "replies": await client.get(f"/api/v1/comments/{viewer_comment['id']}/replies"),
        "comment": await client.get(f"/api/v1/comments/{op_reply['id']}"),
        "search": await client.get("/api/v1/search", params={"q": "unbearable"}),
        "profile_posts": await client.get("/api/v1/users/secret_sam/posts", headers=viewer_h),
        "notifications": await client.get("/api/v1/notifications", headers=viewer_h),
    }
    for name, response in responses.items():
        assert response.status_code == 200, (name, response.text)
        _assert_no_identity(response.json(), *secrets)

    # The post is still discoverable everywhere it should be (not just hidden).
    assert pid in responses["latest"].text and pid in responses["search"].text
    assert pid in responses["following"].text  # via the followed topic, not the followed author
    assert pid not in responses["profile_posts"].text
    profile = (await client.get("/api/v1/users/secret_sam")).json()
    assert profile["post_count"] == 0 and profile["solved_count"] == 0

    # The author still sees it as their own.
    own = (await client.get(f"/api/v1/posts/{pid}", headers=author_h)).json()
    assert own["is_own"] is True and "author" not in own
    own_profile = (await client.get("/api/v1/users/secret_sam/posts", headers=author_h)).json()
    assert pid in [p["id"] for p in own_profile["items"]]


async def test_following_feed_excludes_anonymous_posts_of_followed_users(client: httpx.AsyncClient):
    author, author_h = await make_user("anon_author")
    _, viewer_h = await make_user("follower")
    await client.post("/api/v1/users/anon_author/follow", headers=viewer_h)
    public = await create_rant(
        client, author_h, title="Public rant about traffic", category="commute"
    )
    anon = await create_rant(
        client, author_h, title="Secret rant about traffic", category="commute", is_anonymous=True
    )
    ids = [
        p["id"]
        for p in (await client.get("/api/v1/feed/following", headers=viewer_h)).json()["items"]
    ]
    assert public["id"] in ids and anon["id"] not in ids
