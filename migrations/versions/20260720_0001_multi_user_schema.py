"""Create the initial multi-user service schema."""

from alembic import op

from coastal_web.database import metadata


revision = "20260720_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind())
