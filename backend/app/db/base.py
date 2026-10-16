"""Declarative base + model registry for Alembic."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import every model here so Alembic autogenerate sees them.
from app.models import credit, document, user  # noqa: E402,F401
