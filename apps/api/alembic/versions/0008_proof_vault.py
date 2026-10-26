"""Immutable evidence snapshots and signer queue; preserve unsigned legacy rows."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0008_proof_vault"
down_revision = "0007_recovery"
branch_labels = None
depends_on = None


def identity():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade():
    op.add_column(
        "evaluations",
        sa.Column("proof_native", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.alter_column("evaluations", "proof_native", server_default=sa.true())
    op.create_table(
        "evidence_snapshots",
        *identity(),
        sa.Column("evaluation_id", sa.Uuid(), sa.ForeignKey("evaluations.id"), nullable=False),
        sa.Column("watermark", sa.BigInteger(), nullable=False),
        sa.Column("supersedes", sa.Uuid(), sa.ForeignKey("evidence_snapshots.id")),
        sa.Column("internal_bundle", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("evaluation_id", "watermark", name="uq_proof_snapshot"),
    )
    op.create_table(
        "evidence_receipts",
        *identity(),
        sa.Column("snapshot_id", sa.Uuid(), sa.ForeignKey("evidence_snapshots.id"), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), sa.ForeignKey("evaluations.id"), nullable=False),
        sa.Column("subject_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("profile", sa.String(24), nullable=False),
        sa.Column("watermark", sa.BigInteger(), nullable=False),
        sa.Column("envelope", JSONB(), nullable=False),
        sa.Column("bundle", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("snapshot_id", "subject_id", "profile", name="uq_proof_projection"),
    )
    op.create_table(
        "evidence_requests",
        *identity(),
        sa.Column("evaluation_id", sa.Uuid(), sa.ForeignKey("evaluations.id"), nullable=False),
        sa.Column("subject_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("retrospective", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("receipt_id", sa.Uuid(), sa.ForeignKey("evidence_receipts.id")),
        sa.CheckConstraint("state IN ('PENDING','SIGNED','FAILED')", name="proof_request_state"),
    )
    op.create_table(
        "evidence_verifications",
        *identity(),
        sa.Column("evaluation_id", sa.Uuid(), sa.ForeignKey("evaluations.id"), nullable=False),
        sa.Column("subject_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), sa.ForeignKey("evidence_receipts.id")),
        sa.Column("result", JSONB(), nullable=False),
    )
    op.create_table(
        "evidence_exports",
        *identity(),
        sa.Column("evaluation_id", sa.Uuid(), sa.ForeignKey("evaluations.id"), nullable=False),
        sa.Column("subject_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), sa.ForeignKey("evidence_receipts.id"), nullable=False),
    )
    op.create_table(
        "evidence_keys",
        sa.Column("key_id", sa.String(64), primary_key=True),
        sa.Column("public_key", sa.String(160), nullable=False),
        sa.Column("activated_at", sa.String(27), nullable=False),
        sa.Column("retired_at", sa.String(27)),
    )
    op.execute("""CREATE FUNCTION nexus_proof_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Recorded evidence is immutable'; END $$""")
    for table in [
        "security_events",
        "evaluation_results",
        "evidence_snapshots",
        "evidence_receipts",
        "evidence_verifications",
        "evidence_exports",
    ]:
        op.execute(
            f"CREATE TRIGGER immutable_proof BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION nexus_proof_immutable()"
        )
    op.execute("""CREATE FUNCTION nexus_proof_prefix() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM evidence_snapshots WHERE evaluation_id=NEW.evaluation_id
          AND (NEW.sequence IS NULL OR watermark>=NEW.sequence)) THEN
        RAISE EXCEPTION 'Finalized evidence prefix is closed';
      END IF;
      RETURN NEW;
    END $$""")
    # SECURITY DEFINER with safe schema binding is required: ordinary event writers
    # cannot SELECT private snapshots. Resolve the dedicated schema during migration.
    schema = op.get_bind().execute(sa.text("SELECT current_schema()")).scalar_one()
    quoted = op.get_bind().dialect.identifier_preparer.quote(schema)
    op.execute(
        f"ALTER FUNCTION nexus_proof_prefix() SECURITY DEFINER SET search_path TO {quoted}, pg_temp"
    )
    op.execute("REVOKE ALL ON FUNCTION nexus_proof_prefix() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER closed_proof_prefix BEFORE INSERT ON security_events "
        "FOR EACH ROW EXECUTE FUNCTION nexus_proof_prefix()"
    )
    op.execute("""CREATE FUNCTION nexus_proof_epoch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF NEW.proof_native IS DISTINCT FROM OLD.proof_native THEN
        RAISE EXCEPTION 'Capture epoch is immutable'; END IF;
      RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER immutable_proof_epoch BEFORE UPDATE ON evaluations "
        "FOR EACH ROW EXECUTE FUNCTION nexus_proof_epoch()"
    )


def downgrade():
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM evidence_snapshots) THEN "
        "RAISE EXCEPTION 'Preserve signed evidence before downgrade'; END IF; END $$"
    )
    op.execute("DROP TRIGGER immutable_proof_epoch ON evaluations")
    op.execute("DROP FUNCTION nexus_proof_epoch()")
    op.execute("DROP TRIGGER closed_proof_prefix ON security_events")
    op.execute("DROP FUNCTION nexus_proof_prefix()")
    op.execute("DROP TRIGGER immutable_proof ON security_events")
    op.execute("DROP TRIGGER immutable_proof ON evaluation_results")
    for table in [
        "evidence_exports",
        "evidence_verifications",
        "evidence_requests",
        "evidence_receipts",
        "evidence_snapshots",
        "evidence_keys",
    ]:
        op.drop_table(table)
    op.execute("DROP FUNCTION nexus_proof_immutable()")
    op.drop_column("evaluations", "proof_native")
