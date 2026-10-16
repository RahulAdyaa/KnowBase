"""Credit system schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class BalanceResponse(BaseModel):
    balance: int


class LedgerEntryResponse(BaseModel):
    id: int
    amount: int
    balance_after: int
    reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


class HistoryResponse(BaseModel):
    entries: list[LedgerEntryResponse]
    total: int


class TopUpRequest(BaseModel):
    """Stripe-ready: the real flow creates a Checkout Session and credits on webhook."""

    credits: int = Field(gt=0, le=100_000)
    # Stubbed: in production this comes from the Stripe session, not the client.
    stripe_payment_intent_id: str | None = None


class GrantRequest(BaseModel):
    user_id: int
    credits: int = Field(gt=0, le=1_000_000)
    note: str = ""
