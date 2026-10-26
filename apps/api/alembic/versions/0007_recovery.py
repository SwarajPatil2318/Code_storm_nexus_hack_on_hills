"""Durable evaluation intent and recovery observations.

Revision ID: 0007_recovery
Revises: 0006_campaigns
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_recovery"
down_revision = "0006_campaigns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_jobs",
        sa.Column("evaluation_id", sa.Uuid(), sa.ForeignKey("evaluations.id"), primary_key=True),
        sa.Column("runtime_owner", sa.String(36), nullable=True),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=True),
        sa.Column("cleanup", sa.String(16), nullable=False),
        sa.Column("credentials_revoked", sa.Boolean(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("operation IN ('run','probes','destroy')", name="job_operation"),
        sa.CheckConstraint(
            "state IN ('PENDING','RUNNING','RECOVERING','FINISHED')", name="job_state"
        ),
        sa.CheckConstraint("cleanup IN ('PENDING','VERIFIED','FAILED')", name="job_cleanup"),
    )
    op.create_index("ix_evaluation_jobs_runtime_owner", "evaluation_jobs", ["runtime_owner"])


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM evaluation_jobs WHERE state != 'FINISHED'
                   OR cleanup != 'VERIFIED' OR NOT credentials_revoked) THEN
            RAISE EXCEPTION 'Verify job termination and cleanup before recovery downgrade';
        END IF;
    END $$""")
    op.drop_table("evaluation_jobs")
