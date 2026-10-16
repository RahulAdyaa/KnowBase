"""Credit endpoints: balance, history, top-up (Stripe stub)."""

import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.credit import (
    BalanceResponse,
    HistoryResponse,
    LedgerEntryResponse,
    TopUpRequest,
)
from app.services import credits as credit_service

router = APIRouter()
log = get_logger(__name__)
settings = get_settings()


@router.get("/balance", response_model=BalanceResponse)
def balance(db: DbSession, user: CurrentUser):
    return BalanceResponse(balance=credit_service.get_balance(db, user.id))


@router.get("/history", response_model=HistoryResponse)
def history(db: DbSession, user: CurrentUser, limit: int = 50, offset: int = 0):
    if limit > 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "limit must be <= 200")
    entries, total = credit_service.get_history(db, user.id, limit=limit, offset=offset)
    return HistoryResponse(
        entries=[LedgerEntryResponse.model_validate(e) for e in entries], total=total
    )


@router.post("/topup", response_model=BalanceResponse)
def topup(body: TopUpRequest, request: Request, db: DbSession, user: CurrentUser):
    """STUBBED Stripe flow.

    Production flow:
      1. Create a Stripe Checkout Session for `body.credits` (price from env).
      2. Return the checkout URL; frontend redirects the user.
      3. Stripe webhook -> verify signature -> add_credits(..., reason="topup",
         idempotency_key=f"stripe:{payment_intent_id}").

    The stub credits immediately so the UI and ledger can be built end-to-end
    without Stripe keys. Gate with STRIPE_SECRET_KEY presence in production.
    """
    if settings.stripe_secret_key:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "Stripe is configured - finish the Checkout Session integration.",
        )
    idempotency_key = request.headers.get("Idempotency-Key") or f"topup_stub:{uuid.uuid4()}"
    try:
        new_balance = credit_service.add_credits(
            db, user.id, body.credits, "topup",
            idempotency_key=idempotency_key,
            meta={"stub": True},
        )
    except credit_service.DuplicateTransaction:
        new_balance = credit_service.get_balance(db, user.id)
    log.info("credits_topup_stub", extra={"user_id": user.id, "credits": body.credits})
    return BalanceResponse(balance=new_balance)


@router.post("/webhook")
def stripe_webhook(request: Request):
    """TODO: verify stripe_webhook_secret, then credit on checkout.session.completed."""
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Stripe webhook not implemented")
