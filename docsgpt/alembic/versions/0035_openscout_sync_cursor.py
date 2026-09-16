"""Persist the external high-water mark for OpenScout project syncs.

Revision ID: 0035_openscout_sync_cursor
Revises: 0034_openscout_report_sharing
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0035_openscout_sync_cursor"
down_revision: Union[str, None] = "0034_openscout_report_sharing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the latest external object timestamp to each project."""
    op.add_column(
        "intelligence_projects",
        sa.Column("external_updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    """Remove the persisted external sync cursor."""
    op.drop_column("intelligence_projects", "external_updated_at")
