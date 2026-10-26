"""Actual inference campaigns, immutable matched comparisons and case observations.

Revision ID: 0006_campaigns
Revises: 0005_runtime
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0006_campaigns"
down_revision = "0005_runtime"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "comparisons",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "baseline_id", sa.Uuid(), sa.ForeignKey("evaluations.id"), nullable=False, unique=True
        ),
        sa.Column(
            "defended_id", sa.Uuid(), sa.ForeignKey("evaluations.id"), nullable=False, unique=True
        ),
        sa.Column("manifest", JSONB(), nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
    )
    op.create_table(
        "case_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("evaluation_id", sa.Uuid(), sa.ForeignKey("evaluations.id"), nullable=False),
        sa.Column("case_id", sa.String(40), nullable=False),
        sa.Column("case_index", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column("private_guard", JSONB(), nullable=False),
        sa.UniqueConstraint("evaluation_id", "case_id", name="uq_case_identifier"),
        sa.UniqueConstraint("evaluation_id", "case_index", name="uq_case_index"),
        sa.CheckConstraint("case_index >= 0 AND case_index < 40", name="bounded_case_index"),
    )
    op.execute(
        "CREATE FUNCTION immutable_campaign_record() RETURNS trigger LANGUAGE "
        "plpgsql AS $$ BEGIN RAISE EXCEPTION 'Campaign observations and "
        "comparison bindings are immutable'; END $$"
    )
    for table in ("comparisons", "case_records"):
        op.execute(
            f"CREATE TRIGGER immutable_campaign BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION immutable_campaign_record()"
        )


def downgrade():
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM evaluations e LEFT JOIN "
        "runtime_records r ON e.id=r.evaluation_id WHERE e.manifest ? "
        "'campaign' AND (e.status IN ('PROVISIONING','RUNNING','FINALIZING') "
        "OR (r.snapshot IS NOT NULL AND r.snapshot->>'cleanup' != "
        "'VERIFIED'))) THEN RAISE EXCEPTION 'Verify campaign teardown before "
        "downgrade'; END IF; END $$"
    )
    # M4 cannot execute new campaign versions. Preserve only non-executable legacy metadata.
    op.execute("ALTER TABLE evaluations DISABLE TRIGGER sealed_binding")
    op.execute("UPDATE evaluations SET execution_mode='mock' WHERE manifest ? 'campaign'")
    op.execute("ALTER TABLE evaluations ENABLE TRIGGER sealed_binding")
    op.drop_table("case_records")
    op.drop_table("comparisons")
    op.execute("DROP FUNCTION immutable_campaign_record()")
