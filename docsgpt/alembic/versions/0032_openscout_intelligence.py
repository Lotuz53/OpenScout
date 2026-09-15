"""0032 OpenScout intelligence projects, records, runs and reports.

Revision ID: 0032_openscout_intelligence
Revises: 0031_token_usage_cache_tokens
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0032_openscout_intelligence"
down_revision: Union[str, None] = "0031_token_usage_cache_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SOURCE_TYPES = "'documentation', 'issue', 'issue_comment', 'release'"


def upgrade() -> None:
    """Create the Stage A intelligence persistence tables and indexes."""
    op.create_table(
        "intelligence_projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("repository", sa.Text, nullable=False),
        sa.Column("window_start", sa.Date, nullable=False),
        sa.Column("window_end", sa.Date, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            ondelete="RESTRICT",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'syncing', 'ready', 'partial', 'failed')",
            name="intelligence_projects_status_check",
        ),
    )
    op.create_index("intelligence_projects_user_idx", "intelligence_projects", ["user_id"])
    op.execute(
        """
        CREATE TRIGGER intelligence_projects_ensure_user
        BEFORE INSERT OR UPDATE OF user_id ON intelligence_projects
        FOR EACH ROW EXECUTE FUNCTION ensure_user_exists();
        """
    )
    op.execute(
        """
        CREATE TRIGGER intelligence_projects_set_updated_at
        BEFORE UPDATE ON intelligence_projects
        FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*)
        EXECUTE FUNCTION set_updated_at();
        """
    )

    op.create_table(
        "intelligence_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intelligence_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("repository", sa.Text, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("state", sa.Text),
        sa.Column("labels", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("comments_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reactions_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("version", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint(
            "project_id",
            "source_type",
            "external_id",
            name="intelligence_records_project_source_external_uidx",
        ),
        sa.CheckConstraint(
            f"source_type IN ({_SOURCE_TYPES})",
            name="intelligence_records_source_type_check",
        ),
    )
    op.create_index(
        "intelligence_records_project_type_idx",
        "intelligence_records",
        ["project_id", "source_type"],
    )
    op.create_index(
        "intelligence_records_created_idx",
        "intelligence_records",
        ["project_id", "created_at"],
    )
    op.create_index(
        "intelligence_records_labels_gin_idx",
        "intelligence_records",
        ["labels"],
        postgresql_using="gin",
    )

    op.create_table(
        "intelligence_sync_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intelligence_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("counts", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("failures", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("coverage", postgresql.JSONB),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'partial', 'failed')",
            name="intelligence_sync_runs_status_check",
        ),
    )
    op.create_index(
        "intelligence_sync_runs_project_created_idx",
        "intelligence_sync_runs",
        ["project_id", "created_at"],
    )

    op.create_table(
        "intelligence_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("report_data", postgresql.JSONB, nullable=False),
        sa.Column("markdown_path", sa.Text),
        sa.Column("pdf_path", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            ondelete="RESTRICT",
            deferrable=True,
            initially="IMMEDIATE",
        ),
    )
    op.create_index("intelligence_reports_user_idx", "intelligence_reports", ["user_id"])
    op.execute(
        """
        CREATE TRIGGER intelligence_reports_ensure_user
        BEFORE INSERT OR UPDATE OF user_id ON intelligence_reports
        FOR EACH ROW EXECUTE FUNCTION ensure_user_exists();
        """
    )
    op.execute(
        """
        CREATE TRIGGER intelligence_reports_set_updated_at
        BEFORE UPDATE ON intelligence_reports
        FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*)
        EXECUTE FUNCTION set_updated_at();
        """
    )

    op.create_table(
        "intelligence_topic_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intelligence_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_id", sa.Text, nullable=False),
        sa.Column("algorithm_version", sa.Text, nullable=False),
        sa.Column("clusters", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "project_id",
            "snapshot_id",
            "algorithm_version",
            name="intelligence_topic_runs_snapshot_uidx",
        ),
    )
    op.create_index(
        "intelligence_topic_runs_project_created_idx",
        "intelligence_topic_runs",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    """Drop the Stage A intelligence persistence tables and indexes."""
    op.drop_index("intelligence_topic_runs_project_created_idx", table_name="intelligence_topic_runs")
    op.drop_table("intelligence_topic_runs")

    op.execute("DROP TRIGGER IF EXISTS intelligence_reports_set_updated_at ON intelligence_reports;")
    op.execute("DROP TRIGGER IF EXISTS intelligence_reports_ensure_user ON intelligence_reports;")
    op.drop_index("intelligence_reports_user_idx", table_name="intelligence_reports")
    op.drop_table("intelligence_reports")

    op.drop_index("intelligence_sync_runs_project_created_idx", table_name="intelligence_sync_runs")
    op.drop_table("intelligence_sync_runs")

    op.drop_index("intelligence_records_labels_gin_idx", table_name="intelligence_records")
    op.drop_index("intelligence_records_created_idx", table_name="intelligence_records")
    op.drop_index("intelligence_records_project_type_idx", table_name="intelligence_records")
    op.drop_table("intelligence_records")

    op.execute("DROP TRIGGER IF EXISTS intelligence_projects_set_updated_at ON intelligence_projects;")
    op.execute("DROP TRIGGER IF EXISTS intelligence_projects_ensure_user ON intelligence_projects;")
    op.drop_index("intelligence_projects_user_idx", table_name="intelligence_projects")
    op.drop_table("intelligence_projects")
