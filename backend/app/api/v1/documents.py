"""Document upload + management. Ingestion runs as a background task."""

import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, rate_limit
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.document import Document, DocumentStatus
from app.schemas.document import DocumentListResponse, DocumentResponse
from app.services.embeddings import get_embedding_provider
from app.services.rag import ingest_document
from app.services.vectorstore import get_vector_store

router = APIRouter()
log = get_logger(__name__)
settings = get_settings()

from app.services.extractors import supported_types

ALLOWED_EXTENSIONS = set(supported_types())


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("upload", settings.rate_limit_upload_per_minute))],
)
async def upload_document(
    file: UploadFile, background_tasks: BackgroundTasks, db: DbSession, user: CurrentUser
):
    filename = file.filename or "upload.bin"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )
    raw = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")
    if not raw.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")

    # Persist the raw bytes so the background task survives deploys/restarts.
    os.makedirs(settings.upload_dir, exist_ok=True)
    blob_path = os.path.join(settings.upload_dir, f"{uuid.uuid4()}{ext}")
    with open(blob_path, "wb") as f:
        f.write(raw)

    doc = Document(
        owner_id=user.id,
        filename=filename,
        content_type=file.content_type or "",
        size_bytes=len(raw),
        status=DocumentStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    background_tasks.add_task(
        _ingest_from_disk, doc.id, blob_path, user.id
    )
    log.info("document_uploaded", extra={"document_id": doc.id, "user_id": user.id})
    return doc


def _ingest_from_disk(document_id: int, blob_path: str, user_id: int):
    """Background-task wrapper: fresh DB session, cleanup afterwards."""
    from app.db.session import get_session_factory

    db = get_session_factory()()
    try:
        with open(blob_path, "rb") as f:
            raw = f.read()
        ingest_document(db, document_id, raw, get_embedding_provider(), get_vector_store())
    finally:
        db.close()
        try:
            os.remove(blob_path)
        except OSError:
            pass


@router.get("", response_model=DocumentListResponse)
def list_documents(db: DbSession, user: CurrentUser, limit: int = 50, offset: int = 0):
    q = select(Document).where(Document.owner_id == user.id).order_by(Document.id.desc())
    total = db.scalar(
        select(func.count(Document.id)).where(Document.owner_id == user.id)
    )
    docs = list(db.scalars(q.limit(limit).offset(offset)))
    return DocumentListResponse(documents=docs, total=total)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: int, db: DbSession, user: CurrentUser):
    doc = _owned(db, user.id, document_id)
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, db: DbSession, user: CurrentUser):
    doc = _owned(db, user.id, document_id)
    get_vector_store().delete_document(db, user.id, doc.id)
    db.delete(doc)
    db.commit()
    log.info("document_deleted", extra={"document_id": document_id, "user_id": user.id})


def _owned(db: DbSession, user_id: int, document_id: int) -> Document:
    doc = db.scalar(
        select(Document).where(Document.id == document_id, Document.owner_id == user_id)
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc
