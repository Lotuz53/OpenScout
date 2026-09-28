"""Track OpenScout sync liveness for worker recovery.

Revision ID: 0036_openscout_sync_liveness
Revises: 0035_openscout_sync_cursor
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0036_openscout_sync_liveness"
down_revision: Union[str, None] = "0035_openscout_sync_cursor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a heartbeat timestamp used to distinguish active and stale runs."""
    op.add_column(
        "intelligence_sync_runs",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        """
        UPDATE intelligence_sync_runs
        SET last_heartbeat_at = started_at
        WHERE last_heartbeat_at IS NULL
          AND started_at IS NOT NULL
        """
    )
    op.create_index(
        "intelligence_sync_runs_status_heartbeat_idx",
        "intelligence_sync_runs",
        ["status", "last_heartbeat_at"],
    )


def downgrade() -> None:
    """Remove sync liveness tracking."""
    op.drop_index(
        "intelligence_sync_runs_status_heartbeat_idx",
        table_name="intelligence_sync_runs",
    )
    op.drop_column("intelligence_sync_runs", "last_heartbeat_at")
