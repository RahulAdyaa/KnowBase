"""Application entrypoint: `uvicorn app.main:app`."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.middleware import RequestContextMiddleware

settings = get_settings()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging("DEBUG" if settings.debug else "INFO")
    log.info("app_startup", extra={"env": settings.environment})
    if settings.vector_backend == "pgvector":
        # Ensure the extension exists (idempotent). Migrations own the schema.
        # Wrapped defensively: a failed extension check must not kill boot
        # (readiness probe reports DB health separately).
        try:
            from app.db.session import get_session_factory

            db = get_session_factory()()
            try:
                db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            log.warning("vector_extension_setup_failed", extra={"err": str(exc)})
    yield
    log.info("app_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid request", "errors": exc.errors()},
        )

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
