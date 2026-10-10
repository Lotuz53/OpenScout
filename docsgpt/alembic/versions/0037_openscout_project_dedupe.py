"""Add non-destructive deduplication for equivalent OpenScout projects.

Revision ID: 0037_openscout_project_dedupe
Revises: 0036_openscout_sync_liveness
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0037_openscout_project_dedupe"
down_revision: Union[str, None] = "0036_openscout_sync_liveness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a partial unique key while preserving pre-existing duplicates."""
    op.add_column(
        "intelligence_projects",
        sa.Column("project_dedupe_key", sa.Text),
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY user_id, repository, window_start, window_end
                    ORDER BY created_at ASC, id ASC
                ) AS project_rank
            FROM intelligence_projects
        )
        UPDATE intelligence_projects AS projects
        SET project_dedupe_key = concat_ws(
            chr(31),
            projects.user_id,
            projects.repository,
            projects.window_start::text,
            projects.window_end::text
        )
        FROM ranked
        WHERE projects.id = ranked.id
          AND ranked.project_rank = 1
        """
    )
    op.create_index(
        "intelligence_projects_dedupe_key_uidx",
        "intelligence_projects",
        ["project_dedupe_key"],
        unique=True,
        postgresql_where=sa.text("project_dedupe_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove the project deduplication key and partial index."""
    op.drop_index(
        "intelligence_projects_dedupe_key_uidx",
        table_name="intelligence_projects",
    )
    op.drop_column("intelligence_projects", "project_dedupe_key")
