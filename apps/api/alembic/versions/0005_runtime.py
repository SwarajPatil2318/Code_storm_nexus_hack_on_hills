"""Isolated Docker mode and sanitized persistent runtime proof snapshots.

Revision ID: 0005_runtime
Revises: 0004_classification
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0005_runtime"
down_revision = "0004_classification"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("execution_mode", "evaluations", type_="check")
    op.create_check_constraint(
        "execution_mode",
        "evaluations",
        "execution_mode IN ('mock','production','local_mock','isolated_docker')",
    )
    op.create_table(
        "runtime_records",
        sa.Column("evaluation_id", sa.Uuid(), sa.ForeignKey("evaluations.id"), primary_key=True),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade():
    # Preserve metadata as non-executable legacy records; never turn Docker runs into local runs.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM evaluations e LEFT JOIN runtime_records r "
        "ON e.id=r.evaluation_id WHERE e.execution_mode='isolated_docker' AND "
        "(e.status IN ('PROVISIONING','RUNNING','FINALIZING') OR "
        "(r.snapshot IS NOT NULL AND r.snapshot->>'cleanup' != 'VERIFIED'))) "
        "THEN RAISE EXCEPTION 'Verify Docker cleanup before downgrade'; END IF; END $$"
    )
    op.execute("ALTER TABLE evaluations DISABLE TRIGGER sealed_binding")
    op.execute(
        "UPDATE evaluations SET execution_mode='mock' WHERE execution_mode='isolated_docker'"
    )
    op.execute("ALTER TABLE evaluations ENABLE TRIGGER sealed_binding")
    op.drop_table("runtime_records")
    op.drop_constraint("execution_mode", "evaluations", type_="check")
    op.create_check_constraint(
        "execution_mode", "evaluations", "execution_mode IN ('mock','production','local_mock')"
    )
