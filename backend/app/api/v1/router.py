"""v1 API router assembly."""

from fastapi import APIRouter

from app.api.v1 import admin, auth, chat, credits, documents, health, users

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/admin/users", tags=["admin"])
api_router.include_router(admin.router, prefix="/admin/credits", tags=["admin"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(credits.router, prefix="/credits", tags=["credits"])
