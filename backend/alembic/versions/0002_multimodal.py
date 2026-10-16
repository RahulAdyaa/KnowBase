"""Add multimodal metadata to document_chunks.

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("modality", sa.String(length=16), nullable=False, server_default="text"),
    )
    op.add_column("document_chunks", sa.Column("page_number", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("timestamp_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "timestamp_ms")
    op.drop_column("document_chunks", "page_number")
    op.drop_column("document_chunks", "modality")
