"""Admin-only credit operations."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, DbSession
from app.core.logging import get_logger
from app.schemas.credit import BalanceResponse, GrantRequest
from app.services import credits as credit_service

router = APIRouter()
log = get_logger(__name__)


@router.post("/grant", response_model=BalanceResponse)
def grant_credits(body: GrantRequest, db: DbSession, admin: AdminUser):
    """Grant credits to any user (support / promo / compensation)."""
    from app.models.user import User

    target = db.get(User, body.user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    new_balance = credit_service.add_credits(
        db, target.id, body.credits, "grant",
        meta={"granted_by": admin.id, "note": body.note},
    )
    log.info(
        "credits_granted_by_admin",
        extra={"admin_id": admin.id, "user_id": target.id, "credits": body.credits},
    )
    return BalanceResponse(balance=new_balance)
