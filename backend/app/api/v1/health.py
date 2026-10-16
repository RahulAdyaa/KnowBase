"""Health, readiness and Prometheus metrics."""

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.redis import get_redis

router = APIRouter()


@router.get("/health")
def health():
    """Liveness: is the process alive?"""
    return {"status": "ok"}


@router.get("/ready")
def ready(db: DbSession):
    """Readiness: can we serve traffic? Checks DB + Redis."""
    checks = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
    redis_client = get_redis()
    checks["redis"] = "ok" if redis_client else "unavailable"
    all_ok = all(v == "ok" for v in checks.values())
    return {"ready": all_ok, "checks": checks}


@router.get("/metrics")
def metrics():
    """Prometheus scrape endpoint."""
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except ImportError:
        return Response("prometheus_client not installed", status_code=501)
