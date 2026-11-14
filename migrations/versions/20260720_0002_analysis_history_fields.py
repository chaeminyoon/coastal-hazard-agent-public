"""Preserve analysis history type and SQL query count."""

import sqlalchemy as sa
from alembic import op

revision = "20260720_0002"
down_revision = "20260720_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("analysis_runs")
    }
    if "kind" not in columns:
        op.add_column(
            "analysis_runs",
            sa.Column("kind", sa.String(length=30), nullable=False, server_default="query"),
        )
    if "query_count" not in columns:
        op.add_column(
            "analysis_runs",
            sa.Column("query_count", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("analysis_runs")
    }
    if "query_count" in columns:
        op.drop_column("analysis_runs", "query_count")
    if "kind" in columns:
        op.drop_column("analysis_runs", "kind")
