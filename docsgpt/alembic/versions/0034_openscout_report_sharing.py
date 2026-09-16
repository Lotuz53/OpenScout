"""Add hashed, revocable public links for OpenScout reports.

Revision ID: 0034_openscout_report_sharing
Revises: 0033_openscout_incremental_sync
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0034_openscout_report_sharing"
down_revision: Union[str, None] = "0033_openscout_incremental_sync"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the report-share digest and lifecycle timestamps."""
    op.add_column(
        "intelligence_reports",
        sa.Column("share_token_hash", sa.CHAR(length=64)),
    )
    op.add_column(
        "intelligence_reports",
        sa.Column("shared_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "intelligence_reports",
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "intelligence_reports_share_token_hash_uidx",
        "intelligence_reports",
        ["share_token_hash"],
        unique=True,
        postgresql_where=sa.text("share_token_hash IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove report sharing state."""
    op.drop_index(
        "intelligence_reports_share_token_hash_uidx",
        table_name="intelligence_reports",
    )
    op.drop_column("intelligence_reports", "revoked_at")
    op.drop_column("intelligence_reports", "shared_at")
    op.drop_column("intelligence_reports", "share_token_hash")
