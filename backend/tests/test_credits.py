"""Credit system tests: signup bonus, deduction, idempotency, grants."""

import pytest
from sqlalchemy import select

from app.models.credit import CreditLedger
from app.models.user import Role, User
from app.services import credits as credit_service
from tests.conftest import auth_headers


def test_signup_bonus_credited(client, db_session):
    headers = auth_headers(client, "bonus@example.com")
    resp = client.get("/api/v1/credits/balance", headers=headers)
    assert resp.status_code == 200
    from app.core.config import get_settings

    assert resp.json()["balance"] == get_settings().signup_bonus_credits


def test_deduct_and_insufficient(db_session):
    user = User(email="spend@example.com", hashed_password="x", role=Role.USER)
    db_session.add(user)
    db_session.commit()

    credit_service.add_credits(db_session, user.id, 5, "test_grant", idempotency_key="k1")
    d = credit_service.deduct_credits(db_session, user.id, 3, "chat_query", idempotency_key="k2")
    assert d.charged == 3 and d.balance_after == 2

    with pytest.raises(credit_service.InsufficientCredits):
        credit_service.deduct_credits(db_session, user.id, 10, "chat_query", idempotency_key="k3")
    # Failed deduction leaves the balance untouched.
    assert credit_service.get_balance(db_session, user.id) == 2


def test_idempotent_deduction(db_session):
    user = User(email="idem@example.com", hashed_password="x", role=Role.USER)
    db_session.add(user)
    db_session.commit()
    credit_service.add_credits(db_session, user.id, 10, "test_grant", idempotency_key="g1")

    first = credit_service.deduct_credits(db_session, user.id, 4, "chat_query", idempotency_key="same-key")
    second = credit_service.deduct_credits(db_session, user.id, 4, "chat_query", idempotency_key="same-key")
    assert first.balance_after == second.balance_after == 6
    # Only one ledger row for the replayed key.
    rows = db_session.scalars(select(CreditLedger).where(CreditLedger.idempotency_key == "same-key")).all()
    assert len(rows) == 1


def test_ledger_history_endpoint(client):
    headers = auth_headers(client, "history@example.com")
    resp = client.get("/api/v1/credits/history", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1  # at least the signup bonus
    assert any(e["reason"] == "signup_bonus" for e in body["entries"])


def test_chat_without_credits_returns_402(client, db_session):
    """The credit gate is fail-closed: 0 balance -> 402, no LLM call."""
    headers = auth_headers(client, "broke@example.com")
    user = db_session.scalar(select(User).where(User.email == "broke@example.com"))
    # Drain the signup bonus directly.
    bal = credit_service.get_balance(db_session, user.id)
    credit_service.deduct_credits(db_session, user.id, bal, "test_drain", idempotency_key="drain1")

    resp = client.post("/api/v1/chat/ask", headers=headers, json={"message": "hello"})
    assert resp.status_code == 402, resp.text


def test_admin_grant_requires_admin(client, db_session):
    user_headers = auth_headers(client, "regular@example.com")
    target = db_session.scalar(select(User).where(User.email == "regular@example.com"))

    # Non-admin is forbidden.
    resp = client.post(
        "/api/v1/admin/credits/grant",
        headers=user_headers,
        json={"user_id": target.id, "credits": 100},
    )
    assert resp.status_code == 403

    # Roles are read from the DB per request, so promotion takes effect
    # immediately (and demotion revokes immediately) - no re-login needed.
    target.role = Role.ADMIN
    db_session.commit()
    resp = client.post(
        "/api/v1/admin/credits/grant",
        headers=user_headers,
        json={"user_id": target.id, "credits": 100, "note": "promo"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["balance"] >= 100

    # Demotion revokes instantly too.
    target.role = Role.USER
    db_session.commit()
    resp = client.post(
        "/api/v1/admin/credits/grant",
        headers=user_headers,
        json={"user_id": target.id, "credits": 100},
    )
    assert resp.status_code == 403
