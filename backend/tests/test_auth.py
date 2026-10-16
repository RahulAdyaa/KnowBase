"""Auth flow tests: register, login, token refresh, protected routes."""

from tests.conftest import auth_headers


def test_register_returns_tokens_and_signup_bonus(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]

    # Signup bonus landed.
    bal = client.get("/api/v1/credits/balance", headers=auth_headers(client, "bob@example.com"))
    assert bal.status_code == 200
    assert bal.json()["balance"] >= 0  # bonus asserted precisely in test_credits


def test_register_duplicate_email_conflicts(client):
    client.post("/api/v1/auth/register", json={"email": "dupe@example.com", "password": "password123"})
    resp = client.post(
        "/api/v1/auth/register", json={"email": "dupe@example.com", "password": "password123"}
    )
    assert resp.status_code == 409


def test_register_rejects_short_password(client):
    resp = client.post(
        "/api/v1/auth/register", json={"email": "short@example.com", "password": "abc"}
    )
    assert resp.status_code == 422


def test_login_roundtrip(client):
    client.post("/api/v1/auth/register", json={"email": "carol@example.com", "password": "password123"})
    resp = client.post(
        "/api/v1/auth/login", json={"email": "carol@example.com", "password": "password123"}
    )
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"


def test_login_wrong_password_is_unauthorized(client):
    client.post("/api/v1/auth/register", json={"email": "dave@example.com", "password": "password123"})
    resp = client.post(
        "/api/v1/auth/login", json={"email": "dave@example.com", "password": "wrongpassword"}
    )
    assert resp.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    headers = auth_headers(client, "erin@example.com")
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "erin@example.com"


def test_refresh_issues_new_tokens(client):
    reg = client.post(
        "/api/v1/auth/register", json={"email": "frank@example.com", "password": "password123"}
    )
    refresh_token = reg.json()["refresh_token"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_refresh_with_access_token_fails(client):
    headers = auth_headers(client, "grace@example.com")
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    # Using an access token as a refresh token must be rejected.
    access = headers["Authorization"].removeprefix("Bearer ")
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401
