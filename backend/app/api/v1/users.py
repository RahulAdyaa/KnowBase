"""Admin user management."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession
from app.models.user import User
from app.schemas.auth import UserResponse

router = APIRouter()


@router.get("", response_model=list[UserResponse])
def list_users(db: DbSession, admin: AdminUser, limit: int = 50, offset: int = 0):
    users = list(db.scalars(select(User).order_by(User.id).limit(limit).offset(offset)))
    return users


@router.post("/{user_id}/disable", response_model=UserResponse)
def disable_user(user_id: int, db: DbSession, admin: AdminUser):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot disable yourself")
    user.is_active = False
    db.commit()
    return user


@router.post("/{user_id}/enable", response_model=UserResponse)
def enable_user(user_id: int, db: DbSession, admin: AdminUser):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user.is_active = True
    db.commit()
    return user
