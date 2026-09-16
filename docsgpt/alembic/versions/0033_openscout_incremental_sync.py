"""Add incremental synchronization audit state to intelligence records.

Revision ID: 0033_openscout_incremental_sync
Revises: 0032_openscout_intelligence
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0033_openscout_incremental_sync"
down_revision: Union[str, None] = "0032_openscout_intelligence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add state used to audit incremental sync observations and removals."""
    op.add_column(
        "intelligence_records",
        sa.Column("last_seen_sync_id", sa.Text),
    )
    op.add_column(
        "intelligence_records",
        sa.Column(
            "missing_confirmations",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "intelligence_records",
        sa.Column(
            "active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "intelligence_records",
        sa.Column("deactivated_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "intelligence_records_project_type_active_idx",
        "intelligence_records",
        ["project_id", "source_type", "active"],
    )


def downgrade() -> None:
    """Remove incremental synchronization audit state."""
    op.drop_index(
        "intelligence_records_project_type_active_idx",
        table_name="intelligence_records",
    )
    op.drop_column("intelligence_records", "deactivated_at")
    op.drop_column("intelligence_records", "active")
    op.drop_column("intelligence_records", "missing_confirmations")
    op.drop_column("intelligence_records", "last_seen_sync_id")
