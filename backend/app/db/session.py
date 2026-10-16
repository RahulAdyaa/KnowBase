"""SQLAlchemy engine + session factory.

The engine is created lazily so importing this module never requires a
database driver or a live database - important for unit tests and CLI tools.
"""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine():
    settings = get_settings()
    # NOTE: pool_pre_ping guards against stale connections behind load balancers.
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


@lru_cache
def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency: yields a session, always closes it."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
