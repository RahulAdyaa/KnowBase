"""Test fixtures: isolated sqlite DB per test, FastAPI TestClient.

Only the auth/credit tables are created - the pgvector chunk table is
Postgres-only and excluded by design.
"""

import os

# Must be set BEFORE importing app modules (settings are cached at import).
os.environ["VECTOR_BACKEND"] = "memory"
os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["DATABASE_URL"] = "sqlite:///"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user  # noqa: F401 (keeps import surface honest)
from app.core import security
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.credit import CreditAccount, CreditLedger
from app.models.user import User

# Import models so tables exist in metadata (document models excluded on purpose).
assert User.__tablename__ == "users"
assert CreditAccount.__tablename__ == "credit_accounts"

security.settings.jwt_secret_key = "test-secret"  # isolate from dev env


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        User.__table__,
        CreditAccount.__table__,
        CreditLedger.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine, tables=tables)


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as c:
        yield c


def auth_headers(client: TestClient, email: str = "test@example.com") -> dict:
    """Register a user and return Authorization headers."""
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
