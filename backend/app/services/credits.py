"""Credit accounting: balances, atomic deductions, grants, ledger history.

All mutations are integer-based and idempotent (via `idempotency_key`).
Deductions lock the account row (SELECT ... FOR UPDATE) so concurrent
chat requests cannot overspend.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.credit import CreditAccount, CreditLedger

log = get_logger(__name__)


class InsufficientCredits(Exception):
    pass


class DuplicateTransaction(Exception):
    """Idempotency key already seen - the original result stands."""


@dataclass
class Deduction:
    charged: int
    balance_after: int


def get_or_create_account(db: Session, user_id: int) -> CreditAccount:
    account = db.scalar(select(CreditAccount).where(CreditAccount.user_id == user_id))
    if account is None:
        account = CreditAccount(user_id=user_id, balance=0)
        db.add(account)
        db.flush()
    return account


def get_balance(db: Session, user_id: int) -> int:
    return get_or_create_account(db, user_id).balance


def _record(
    db: Session,
    account: CreditAccount,
    amount: int,
    reason: str,
    idempotency_key: str,
    meta: dict | None = None,
) -> CreditLedger:
    entry = CreditLedger(
        account_id=account.id,
        amount=amount,
        balance_after=account.balance,
        reason=reason,
        idempotency_key=idempotency_key,
        meta_json=json.dumps(meta or {}),
    )
    db.add(entry)
    return entry


def add_credits(
    db: Session,
    user_id: int,
    amount: int,
    reason: str,
    idempotency_key: str | None = None,
    meta: dict | None = None,
) -> int:
    """Grant credits. Returns the new balance."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    key = idempotency_key or f"{reason}:{uuid.uuid4()}"
    if db.scalar(select(CreditLedger).where(CreditLedger.idempotency_key == key)):
        raise DuplicateTransaction(key)
    account = get_or_create_account(db, user_id)
    # Lock the row for the update.
    account = db.scalar(
        select(CreditAccount).where(CreditAccount.id == account.id).with_for_update()
    )
    account.balance += amount
    _record(db, account, amount, reason, key, meta)
    db.commit()
    log.info("credits_granted", extra={"user_id": user_id, "amount": amount, "reason": reason})
    return account.balance


def deduct_credits(
    db: Session,
    user_id: int,
    amount: int,
    reason: str,
    idempotency_key: str | None = None,
    meta: dict | None = None,
) -> Deduction:
    """Atomically deduct credits. Raises InsufficientCredits if balance is too low."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    key = idempotency_key or f"{reason}:{uuid.uuid4()}"
    existing = db.scalar(select(CreditLedger).where(CreditLedger.idempotency_key == key))
    if existing:
        # Idempotent replay: report the original outcome.
        account = db.get(CreditAccount, existing.account_id)
        return Deduction(charged=-existing.amount, balance_after=account.balance)

    account = get_or_create_account(db, user_id)
    account = db.scalar(
        select(CreditAccount).where(CreditAccount.id == account.id).with_for_update()
    )
    if account.balance < amount:
        db.rollback()
        raise InsufficientCredits(f"Need {amount} credits, have {account.balance}")
    account.balance -= amount
    _record(db, account, -amount, reason, key, meta)
    db.commit()
    log.info("credits_deducted", extra={"user_id": user_id, "amount": amount, "reason": reason})
    return Deduction(charged=amount, balance_after=account.balance)


def get_history(db: Session, user_id: int, limit: int = 50, offset: int = 0):
    account = get_or_create_account(db, user_id)
    q = (
        select(CreditLedger)
        .where(CreditLedger.account_id == account.id)
        .order_by(CreditLedger.id.desc())
    )
    total = db.scalar(
        select(func.count(CreditLedger.id)).where(CreditLedger.account_id == account.id)
    )
    entries = list(db.scalars(q.limit(limit).offset(offset)))
    return entries, total
