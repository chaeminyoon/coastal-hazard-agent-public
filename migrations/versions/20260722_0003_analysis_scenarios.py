"""Add persistent spatial analysis scenarios."""

import sqlalchemy as sa
from alembic import op

from coastal_web.database import analysis_scenarios


revision = "20260722_0003"
down_revision = "20260720_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "analysis_scenarios" not in sa.inspect(op.get_bind()).get_table_names():
        analysis_scenarios.create(bind=op.get_bind())


def downgrade() -> None:
    if "analysis_scenarios" in sa.inspect(op.get_bind()).get_table_names():
        analysis_scenarios.drop(bind=op.get_bind())
