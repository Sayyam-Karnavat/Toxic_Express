import json
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select, text, update

import mailer
import oauth
from database import SessionLocal
from models import AuthSession, OAuthAccount, User, UserStatus
from security import REFRESH_COOKIE
from tests.conftest import CSRF, TEST_PASSWORD, client_for_ip, make_user
from utils import utcnow

SIGNUP = {
    "email": "Rae@Example.com",
    "password": "Sup3r-secret-pass",
    "handle": "rae_vents",
    "display_name": "Rae",
}


async def signup(client: httpx.AsyncClient, **overrides: str) -> httpx.Response:
    return await client.post("/api/v1/auth/signup", json={**SIGNUP, **overrides})


# --- Signup / login ----------------------------------------------------------------------------


async def test_signup_creates_account_session_and_sends_verification(client: httpx.AsyncClient):
    r = await signup(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["email"] == "rae@example.com"
    assert body["user"]["email_verified"] is False
    assert body["user"]["has_password"] is True
    assert REFRESH_COOKIE in r.cookies
    cookie_header = r.headers["set-cookie"].lower()
    assert "httponly" in cookie_header and "samesite=lax" in cookie_header
    assert "path=/api/v1/auth" in cookie_header
    assert len(mailer.OUTBOX) == 1 and "verify-email?token=" in mailer.OUTBOX[0].text

    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["handle"] == "rae_vents"


@pytest.mark.parametrize(
    ("override", "status", "code"),
    [
        ({"password": "short"}, 422, "validation_error"),
        ({"password": "aaaaaaaaaaaa"}, 400, "weak_password"),
        ({"password": "rae_vents-123456"}, 400, "weak_password"),
        ({"handle": "admin"}, 422, "validation_error"),
        ({"handle": "Bad Handle!"}, 422, "validation_error"),
        ({"email": "not-an-email"}, 422, "validation_error"),
    ],
)
async def test_signup_validation(client: httpx.AsyncClient, override, status, code):
    r = await signup(client, **override)
    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] == code


async def test_signup_rejects_unknown_fields(client: httpx.AsyncClient):
    r = await client.post("/api/v1/auth/signup", json={**SIGNUP, "role": "admin"})
    assert r.status_code == 422


async def test_signup_duplicates(client: httpx.AsyncClient):
    assert (await signup(client)).status_code == 201
    r = await signup(client, handle="other_handle")
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    r = await signup(client, email="new@example.com")
    assert r.status_code == 409 and r.json()["error"]["code"] == "handle_taken"


async def test_login_success_and_failures(client: httpx.AsyncClient):
    user, _ = await make_user("lena")
    r = await client.post(
        "/api/v1/auth/login", json={"email": "LENA@example.com", "password": TEST_PASSWORD}
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == str(user.id)
    bad = await client.post(
        "/api/v1/auth/login", json={"email": "lena@example.com", "password": "wrong-password"}
    )
    assert bad.status_code == 401
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"}
    )
    assert unknown.status_code == 401
    assert bad.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_banned_user_cannot_login(client: httpx.AsyncClient):
    await make_user("banned_bob", status=UserStatus.banned)
    r = await client.post(
        "/api/v1/auth/login", json={"email": "banned_bob@example.com", "password": TEST_PASSWORD}
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_banned"


async def test_google_only_account_cannot_password_login(client: httpx.AsyncClient):
    await make_user("gonly", password=False)
    r = await client.post(
        "/api/v1/auth/login", json={"email": "gonly@example.com", "password": TEST_PASSWORD}
    )
    assert r.status_code == 401


# --- Refresh rotation --------------------------------------------------------------------------


async def test_refresh_requires_csrf_header(client: httpx.AsyncClient):
    await signup(client)
    r = await client.post("/api/v1/auth/refresh")
    assert r.status_code == 403


async def test_refresh_rotates_and_detects_reuse(client: httpx.AsyncClient):
    first = (await signup(client)).cookies[REFRESH_COOKIE]
    r = await client.post("/api/v1/auth/refresh", headers=CSRF)
    assert r.status_code == 200, r.text
    second = r.cookies[REFRESH_COOKIE]
    assert second != first

    # Replaying the previous token inside the grace window (parallel tab) is tolerated...
    client.cookies.set(REFRESH_COOKIE, first, path="/api/v1/auth")
    r = await client.post("/api/v1/auth/refresh", headers=CSRF)
    assert r.status_code == 200
    assert REFRESH_COOKIE not in r.cookies  # ...but it does not mint a new cookie.

    # Outside the grace window a replay is treated as theft and kills the session.
    async with SessionLocal() as db:
        await db.execute(update(AuthSession).values(rotated_at=utcnow() - timedelta(minutes=5)))
        await db.commit()
    r = await client.post("/api/v1/auth/refresh", headers=CSRF)
    assert r.status_code == 401
    assert (
        'te_refresh=""' in r.headers.get("set-cookie", "")
        or "max-age=0" in r.headers.get("set-cookie", "").lower()
    )
    client.cookies.set(REFRESH_COOKIE, second, path="/api/v1/auth")
    r = await client.post("/api/v1/auth/refresh", headers=CSRF)
    assert r.status_code == 401


async def test_refresh_with_garbage_cookie(client: httpx.AsyncClient):
    client.cookies.set(REFRESH_COOKIE, "not-a-token", path="/api/v1/auth")
    r = await client.post("/api/v1/auth/refresh", headers=CSRF)
    assert r.status_code == 401


# --- Logout ------------------------------------------------------------------------------------


async def test_logout_revokes_access_token_immediately(client: httpx.AsyncClient):
    body = (await signup(client)).json()
    headers = {"Authorization": f"Bearer {body['access_token']}", **CSRF}
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 200
    r = await client.post("/api/v1/auth/logout", headers=headers)
    assert r.status_code == 200
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401
    assert (await client.post("/api/v1/auth/refresh", headers=CSRF)).status_code == 401


async def test_logout_all_and_session_listing(client: httpx.AsyncClient):
    user, headers = await make_user("multi")
    for _ in range(2):
        await client.post(
            "/api/v1/auth/login", json={"email": "multi@example.com", "password": TEST_PASSWORD}
        )
    sessions = (await client.get("/api/v1/me/sessions", headers=headers)).json()
    assert len(sessions) == 3 and sum(s["current"] for s in sessions) == 1
    assert (await client.post("/api/v1/auth/logout-all", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401


async def test_revoke_single_session(client: httpx.AsyncClient):
    user, headers = await make_user("solo")
    sessions = (await client.get("/api/v1/me/sessions", headers=headers)).json()
    r = await client.delete(f"/api/v1/me/sessions/{sessions[0]['id']}", headers=headers)
    assert r.status_code == 200
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401


# --- Tokens ------------------------------------------------------------------------------------


async def test_rejects_tampered_and_unsigned_tokens(client: httpx.AsyncClient):
    user, headers = await make_user("tok")
    token = headers["Authorization"].split()[1]
    payload = jwt.decode(token, options={"verify_signature": False})
    forged = jwt.encode({**payload, "role": "admin"}, "wrong-secret", algorithm="HS256")
    unsigned = jwt.encode(payload, key=None, algorithm="none")
    for bad in (forged, unsigned, "garbage"):
        r = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401


async def test_expired_access_token(client: httpx.AsyncClient):
    from config import settings

    user, headers = await make_user("old")
    payload = jwt.decode(headers["Authorization"].split()[1], options={"verify_signature": False})
    payload["exp"] = int(time.time()) - 10
    expired = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    r = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and "expired" in r.json()["error"]["message"].lower()


# --- Email verification & password reset -------------------------------------------------------


def _token_from_outbox(marker: str) -> str:
    text_body = next(e.text for e in reversed(mailer.OUTBOX) if marker in e.text)
    return parse_qs(urlparse(text_body.split(": ", 1)[1]).query)["token"][0]


async def test_verify_email_single_use(client: httpx.AsyncClient):
    body = (await signup(client)).json()
    token = _token_from_outbox("verify-email")
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": token})
    ).status_code == 200
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["email_verified"] is True
    again = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert again.status_code == 400


async def test_password_reset_flow(client: httpx.AsyncClient):
    user, headers = await make_user("forgetful")
    r = await client.post("/api/v1/auth/forgot-password", json={"email": "forgetful@example.com"})
    assert r.status_code == 202
    token = _token_from_outbox("reset-password")
    r = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "Brand-new-pass-77"}
    )
    assert r.status_code == 200, r.text
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401  # sessions revoked
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "forgetful@example.com", "password": "Brand-new-pass-77"},
    )
    assert login.status_code == 200
    reuse = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "Another-pass-777"}
    )
    assert reuse.status_code == 400


async def test_forgot_password_does_not_reveal_accounts(client: httpx.AsyncClient):
    r = await client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert r.status_code == 202 and mailer.OUTBOX == []


async def test_set_and_change_password(client: httpx.AsyncClient):
    user, headers = await make_user("nopass", password=False)
    r = await client.post(
        "/api/v1/auth/password", headers=headers, json={"password": "Fresh-password-1"}
    )
    assert r.status_code == 200
    r = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"password": "Fresh-password-2", "current_password": "wrong"},
    )
    assert r.status_code == 400
    r = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"password": "Fresh-password-2", "current_password": "Fresh-password-1"},
    )
    assert r.status_code == 200


# --- Rate limits -------------------------------------------------------------------------------


async def test_login_rate_limited_per_email(client: httpx.AsyncClient):
    await make_user("target")
    statuses = []
    for i in range(12):
        async with client_for_ip(f"10.1.0.{i}") as c:
            r = await c.post(
                "/api/v1/auth/login",
                json={"email": "target@example.com", "password": "wrong-guess"},
            )
            statuses.append(r.status_code)
    assert statuses[:10] == [401] * 10
    assert statuses[10:] == [429, 429]


async def test_signup_rate_limited_per_ip(client: httpx.AsyncClient):
    codes = [
        (await signup(client, email=f"u{i}@example.com", handle=f"user_{i}x")).status_code
        for i in range(6)
    ]
    assert codes[:5] == [201] * 5
    assert codes[5] == 429


async def test_rate_limit_response_shape(client: httpx.AsyncClient):
    for _ in range(5):
        await client.post("/api/v1/auth/forgot-password", json={"email": "a@example.com"})
    r = await client.post("/api/v1/auth/forgot-password", json={"email": "a@example.com"})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0
    assert r.json()["error"]["code"] == "rate_limited"


# --- Account deletion --------------------------------------------------------------------------


async def test_delete_account_and_reactivate_by_login(client: httpx.AsyncClient):
    user, headers = await make_user("leaving")
    r = await client.request(
        "DELETE",
        "/api/v1/me",
        headers=headers,
        json={"password": TEST_PASSWORD, "confirm": "DELETE"},
    )
    assert r.status_code == 200, r.text
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401
    assert (await client.get("/api/v1/users/leaving")).status_code == 404
    r = await client.post(
        "/api/v1/auth/login", json={"email": "leaving@example.com", "password": TEST_PASSWORD}
    )
    assert r.status_code == 200
    assert r.json()["user"]["status"] == "active"
    assert r.json()["user"]["deletion_scheduled_at"] is None


async def test_delete_account_requires_password(client: httpx.AsyncClient):
    user, headers = await make_user("keeper")
    r = await client.request(
        "DELETE", "/api/v1/me", headers=headers, json={"password": "nope", "confirm": "DELETE"}
    )
    assert r.status_code == 400


# --- Middleware --------------------------------------------------------------------------------


async def test_security_headers_and_request_id(client: httpx.AsyncClient):
    r = await client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-request-id"]


async def test_body_size_limit(client: httpx.AsyncClient):
    r = await client.post(
        "/api/v1/auth/login",
        content=b"x" * (300 * 1024),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413


async def test_readiness(client: httpx.AsyncClient):
    r = await client.get("/health/ready")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "ok", "redis": "ok"}


# --- Google OAuth ------------------------------------------------------------------------------

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-kid"


def _jwks() -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key()))
    return {"keys": [{**jwk, "kid": _KID, "alg": "RS256", "use": "sig"}]}


def _id_token(flow_nonce: str, **claims: object) -> str:
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id.apps.googleusercontent.com",
        "sub": "google-sub-123",
        "email": "rae@gmail.com",
        "email_verified": True,
        "name": "Rae Google",
        "iat": now,
        "exp": now + 600,
        "nonce": flow_nonce,
        **claims,
    }
    return jwt.encode(payload, _KEY, algorithm="RS256", headers={"kid": _KID})


@pytest.fixture(autouse=True)
def _reset_jwks_cache():
    oauth._jwks.update(keys={}, expires=0.0)


async def _google_roundtrip(
    client: httpx.AsyncClient,
    start_path: str = "/api/v1/auth/google/login",
    headers: dict | None = None,
    **claims: object,
) -> httpx.Response:
    if start_path.endswith("link-url"):
        url = (await client.post(start_path, headers=headers)).json()["url"]
    else:
        url = (await client.get(start_path)).headers["location"]
    params = parse_qs(urlparse(url).query)
    assert params["code_challenge_method"] == ["S256"]
    state, nonce = params["state"][0], params["nonce"][0]
    with respx.mock(assert_all_called=False) as mock:
        mock.post(oauth.GOOGLE_TOKEN_URL).respond(
            200, json={"id_token": _id_token(nonce, **claims)}
        )
        mock.get(oauth.GOOGLE_JWKS_URL).respond(
            200, json=_jwks(), headers={"cache-control": "max-age=600"}
        )
        mock.route(host="test").pass_through()
        return await client.get(
            "/api/v1/auth/google/callback", params={"code": "auth-code", "state": state}
        )


async def test_google_new_user_requires_onboarding(client: httpx.AsyncClient):
    r = await _google_roundtrip(client)
    assert r.status_code == 302
    assert r.headers["location"] == "http://frontend.test/auth/callback?new=1"
    assert REFRESH_COOKIE in r.cookies
    tokens = (await client.post("/api/v1/auth/refresh", headers=CSRF)).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = tokens["user"]
    assert me["email"] == "rae@gmail.com" and me["email_verified"] and not me["has_password"]
    assert me["google_linked"] and me["onboarded"] is False and me["handle"].startswith("rae_")

    blocked = await client.patch("/api/v1/me", headers=headers, json={"bio": "hi"})
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "onboarding_required"
    r = await client.post(
        "/api/v1/me/onboarding",
        headers=headers,
        json={"handle": "rae_rants", "display_name": "Rae", "headline": "Dev"},
    )
    assert r.status_code == 200 and r.json()["onboarded"] is True
    assert (
        await client.patch("/api/v1/me", headers=headers, json={"bio": "hi"})
    ).status_code == 200


async def test_google_returning_user_logs_in(client: httpx.AsyncClient):
    await _google_roundtrip(client)
    async with SessionLocal() as db:
        await db.execute(update(User).values(onboarded=True))
        await db.commit()
    client.cookies.clear()
    r = await _google_roundtrip(client)
    assert r.headers["location"] == "http://frontend.test/auth/callback"
    async with SessionLocal() as db:
        assert len((await db.scalars(select(User))).all()) == 1


async def test_google_links_verified_email_account(client: httpx.AsyncClient):
    user, _ = await make_user("raeacct")
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.id == user.id).values(email="rae@gmail.com"))
        await db.commit()
    r = await _google_roundtrip(client)
    assert r.headers["location"] == "http://frontend.test/auth/callback"
    async with SessionLocal() as db:
        linked = await db.scalar(select(OAuthAccount))
        assert linked.user_id == user.id
        refreshed = await db.get(User, user.id)
        assert refreshed.password_hash is not None  # verified account keeps its password


async def test_google_takes_over_unverified_squatted_account(client: httpx.AsyncClient):
    squatter, squatter_headers = await make_user("squatter", verified=False)
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.id == squatter.id).values(email="rae@gmail.com"))
        await db.commit()
    await _google_roundtrip(client)
    async with SessionLocal() as db:
        user = await db.get(User, squatter.id)
        assert user.password_hash is None and user.email_verified_at is not None
    assert (await client.get("/api/v1/me", headers=squatter_headers)).status_code == 401


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"email_verified": False}, "oauth_failed"),
        ({"aud": "someone-else"}, "oauth_failed"),
        ({"iss": "https://evil.example.com"}, "oauth_failed"),
        ({"exp": int(time.time()) - 3600}, "oauth_failed"),
        ({"nonce": "wrong-nonce"}, "oauth_failed"),
    ],
)
async def test_google_rejects_bad_id_tokens(client: httpx.AsyncClient, claims, expected):
    r = await _google_roundtrip(client, **claims)
    assert r.status_code == 302
    assert r.headers["location"] == f"http://frontend.test/login?error={expected}"
    assert REFRESH_COOKIE not in r.cookies


async def test_google_callback_rejects_unknown_state(client: httpx.AsyncClient):
    r = await client.get("/api/v1/auth/google/callback", params={"code": "x", "state": "forged"})
    assert r.headers["location"] == "http://frontend.test/login?error=oauth_failed"
    r = await client.get("/api/v1/auth/google/callback", params={"error": "access_denied"})
    assert r.headers["location"] == "http://frontend.test/login?error=google_cancelled"


async def test_google_state_is_single_use(client: httpx.AsyncClient):
    url = (await client.get("/api/v1/auth/google/login")).headers["location"]
    params = parse_qs(urlparse(url).query)
    state, nonce = params["state"][0], params["nonce"][0]
    with respx.mock(assert_all_called=False) as mock:
        mock.post(oauth.GOOGLE_TOKEN_URL).respond(200, json={"id_token": _id_token(nonce)})
        mock.get(oauth.GOOGLE_JWKS_URL).respond(200, json=_jwks())
        mock.route(host="test").pass_through()
        first = await client.get(
            "/api/v1/auth/google/callback", params={"code": "c", "state": state}
        )
        second = await client.get(
            "/api/v1/auth/google/callback", params={"code": "c", "state": state}
        )
    assert first.headers["location"].startswith("http://frontend.test/auth/callback")
    assert second.headers["location"] == "http://frontend.test/login?error=oauth_failed"


async def test_google_link_and_unlink(client: httpx.AsyncClient):
    user, headers = await make_user("linker")
    r = await _google_roundtrip(client, "/api/v1/auth/google/link-url", headers)
    assert r.headers["location"] == "http://frontend.test/settings/account?linked=google"
    assert (await client.get("/api/v1/me", headers=headers)).json()["google_linked"] is True
    assert (await client.delete("/api/v1/auth/google", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/me", headers=headers)).json()["google_linked"] is False


async def test_google_unlink_requires_password(client: httpx.AsyncClient):
    await _google_roundtrip(client)
    tokens = (await client.post("/api/v1/auth/refresh", headers=CSRF)).json()
    r = await client.delete(
        "/api/v1/auth/google", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "password_required"


async def test_google_account_cannot_be_linked_twice(client: httpx.AsyncClient):
    await _google_roundtrip(client)  # creates user A owning google-sub-123
    user_b, headers_b = await make_user("bee")
    r = await _google_roundtrip(client, "/api/v1/auth/google/link-url", headers_b)
    assert r.headers["location"] == "http://frontend.test/login?error=google_in_use"


async def test_banned_google_user_cannot_login(client: httpx.AsyncClient):
    await _google_roundtrip(client)
    async with SessionLocal() as db:
        await db.execute(text("UPDATE users SET status = 'banned'"))
        await db.commit()
    client.cookies.clear()
    r = await _google_roundtrip(client)
    assert r.headers["location"] == "http://frontend.test/login?error=account_banned"


async def test_request_logging_at_info_level(client: httpx.AsyncClient, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="toxic_express"):
        r = await client.get("/health", headers={"X-Request-ID": "req-123"})
    assert r.status_code == 200 and r.headers["x-request-id"] == "req-123"
    assert any("GET /health -> 200" in m for m in caplog.messages)
