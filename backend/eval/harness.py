"""Eval harness: builds an isolated environment and ingests the corpus
through the REAL platform pipeline (chunking -> embeddings -> vector store).

Must be imported before any app modules (settings are cached at import).
"""

import os

os.environ["VECTOR_BACKEND"] = "memory"
os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("JWT_SECRET_KEY", "eval-only-secret-key-min-32-chars!!")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core import security  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models.credit import CreditAccount, CreditLedger  # noqa: E402
from app.models.document import Document, DocumentChunk, DocumentStatus  # noqa: E402
from app.models.user import Role, User  # noqa: E402
from app.services.chunking import estimate_tokens  # noqa: E402
from app.services.embeddings import FakeEmbeddingProvider  # noqa: E402
from app.services.rag import ingest_document  # noqa: E402
from app.services.vectorstore import InMemoryVectorStore  # noqa: E402

from eval.corpus import DOCS  # noqa: E402

security.settings.jwt_secret_key = "eval-only-secret-key-min-32-chars!!"


class EvalEnv:
    def __init__(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        tables = [
            User.__table__,
            CreditAccount.__table__,
            CreditLedger.__table__,
            Document.__table__,
            DocumentChunk.__table__,
        ]
        Base.metadata.create_all(engine, tables=tables)
        self.session = sessionmaker(bind=engine, expire_on_commit=False)()
        self.store = InMemoryVectorStore()
        self.embedder = FakeEmbeddingProvider()
        self.doc_key_to_id: dict[str, int] = {}

        user = User(
            email="eval@example.com",
            hashed_password=security.hash_password("password123"),
            role=Role.USER,
        )
        self.session.add(user)
        self.session.commit()
        self.user_id = user.id

    def ingest(self, doc_keys: list[str] | None = None) -> None:
        """Ingest corpus docs via the real ingestion pipeline."""
        for key in doc_keys or list(DOCS.keys()):
            spec = DOCS[key]
            raw = spec["text"].encode("utf-8")
            doc = Document(
                owner_id=self.user_id,
                filename=spec["filename"],
                content_type="text/plain",
                size_bytes=len(raw),
                status=DocumentStatus.PENDING,
            )
            self.session.add(doc)
            self.session.commit()
            ingest_document(self.session, doc.id, raw, self.embedder, self.store)
            self.session.refresh(doc)
            assert doc.status == DocumentStatus.READY, f"{key} ingest failed: {doc.error}"
            assert doc.chunk_count == 1, f"{key}: expected 1 chunk, got {doc.chunk_count}"
            self.doc_key_to_id[key] = doc.id

    def chunk_id_to_doc_key(self, chunk) -> str | None:
        for key, doc_id in self.doc_key_to_id.items():
            if chunk.document_id == doc_id:
                return key
        return None

    def close(self) -> None:
        self.session.close()


def token_estimate(text: str) -> int:
    return estimate_tokens(text)
