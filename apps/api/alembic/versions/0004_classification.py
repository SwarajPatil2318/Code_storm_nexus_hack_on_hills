"""Explicit immutable artifact visibility classification.

Revision ID: 0004_classification
Revises: 0003_mediation
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_classification"
down_revision = "0003_mediation"
branch_labels = None
depends_on = None


def upgrade():
    # Disable only our immutability trigger for this controlled schema backfill.
    op.add_column("artifact_versions", sa.Column("visibility", sa.String(40), nullable=True))
    op.execute("ALTER TABLE artifact_versions DISABLE TRIGGER immutable_version")
    op.execute(
        "UPDATE artifact_versions SET visibility=CASE domain WHEN 'RED' THEN "
        "'RED_CONFIDENTIAL' WHEN 'BLUE' THEN 'BLUE_CONFIDENTIAL' ELSE 'TRUSTED_INTERNAL' END"
    )
    op.execute("ALTER TABLE artifact_versions ENABLE TRIGGER immutable_version")
    op.alter_column("artifact_versions", "visibility", nullable=False)


def downgrade():
    op.drop_column("artifact_versions", "visibility")
