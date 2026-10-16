"""Credit system: account balances + immutable transaction ledger.

Money-adjacent data: balances are integers (no floats), every mutation writes
a ledger row, and deductions use SELECT ... FOR UPDATE so concurrent requests
can't double-spend.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CreditAccount(Base):
    __tablename__ = "credit_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="credit_account")
    ledger_entries: Mapped[list["CreditLedger"]] = relationship(
        "CreditLedger", back_populates="account", cascade="all, delete-orphan"
    )


class CreditLedger(Base):
    """Append-only ledger. `amount` is signed: negative = spend, positive = grant."""

    __tablename__ = "credit_ledger"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_ledger_idempotency"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("credit_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. chat_query, topup, grant, signup_bonus
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    meta_json: Mapped[str] = mapped_column(String(2000), default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    account: Mapped[CreditAccount] = relationship("CreditAccount", back_populates="ledger_entries")
