"""Immutable versions and local mediated lifecycle. No workload provisioning.

Revision ID: 0003_mediation
Revises: 0002_identity
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0003_mediation"
down_revision = "0002_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "artifact_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id")),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("domain", sa.String(24), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_ref", sa.String(80), nullable=False, unique=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('attack','defence','model','flow_policy')", name="version_kind"
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="version_sha"),
        sa.CheckConstraint("byte_size > 0 AND byte_size <= 65536", name="version_size"),
    )
    op.create_table(
        "version_grants",
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("artifact_versions.id"), primary_key=True),
        sa.Column("red_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
    )
    for name in ("red_version_id", "blue_version_id", "model_version_id", "flow_policy_version_id"):
        op.add_column("evaluations", sa.Column(name, sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_evaluation_{name}", "evaluations", "artifact_versions", [name], ["id"]
        )
    op.add_column("evaluations", sa.Column("manifest", JSONB(), nullable=True))
    op.add_column("evaluations", sa.Column("manifest_digest", sa.String(64), nullable=True))
    for name in ("blue_approved", "worker_claimed"):
        op.add_column(
            "evaluations",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
    op.add_column(
        "evaluations", sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("security_events", sa.Column("sequence", sa.BigInteger(), nullable=True))
    op.create_unique_constraint(
        "uq_event_sequence", "security_events", ["evaluation_id", "sequence"]
    )
    op.drop_constraint("evaluation_status", "evaluations", type_="check")
    op.execute(
        "UPDATE evaluations SET status = CASE status WHEN 'draft' THEN 'CREATED' "
        "WHEN 'queued' THEN 'CREATED' ELSE upper(status) END"
    )
    op.create_check_constraint(
        "evaluation_status",
        "evaluations",
        "status IN ('CREATED','COMMITTED','SEALED','PROVISIONING','RUNNING','FINALIZING',"
        "'COMPLETED','DESTROYED','FAILED','CANCELLED')",
    )
    op.drop_constraint("execution_mode", "evaluations", type_="check")
    op.create_check_constraint(
        "execution_mode", "evaluations", "execution_mode IN ('mock','production','local_mock')"
    )
    op.execute("""CREATE FUNCTION nexus_version_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Immutable artifact version'; END; $$""")
    op.execute("""CREATE TRIGGER immutable_version BEFORE UPDATE OR DELETE ON artifact_versions
               FOR EACH ROW EXECUTE FUNCTION nexus_version_immutable()""")
    op.execute("""CREATE FUNCTION nexus_sealed_binding() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.manifest_digest IS NOT NULL AND
        (NEW.manifest,NEW.manifest_digest,NEW.red_version_id,NEW.blue_version_id,
         NEW.model_version_id,NEW.flow_policy_version_id,NEW.owner_id,NEW.execution_mode)
        IS DISTINCT FROM
        (OLD.manifest,OLD.manifest_digest,OLD.red_version_id,OLD.blue_version_id,
         OLD.model_version_id,OLD.flow_policy_version_id,OLD.owner_id,OLD.execution_mode)
      THEN RAISE EXCEPTION 'Committed evaluation bindings immutable'; END IF;
      IF OLD.sealed_at IS NOT NULL AND (NEW.sealed_at IS DISTINCT FROM OLD.sealed_at
          OR NEW.blue_approved IS DISTINCT FROM OLD.blue_approved)
      THEN RAISE EXCEPTION 'Sealed evaluation immutable'; END IF;
      RETURN NEW;
    END; $$""")
    op.execute("""CREATE TRIGGER sealed_binding BEFORE UPDATE ON evaluations
               FOR EACH ROW EXECUTE FUNCTION nexus_sealed_binding()""")


def downgrade():
    op.execute("DROP TRIGGER sealed_binding ON evaluations")
    op.execute("DROP FUNCTION nexus_sealed_binding()")
    op.execute("DROP TRIGGER immutable_version ON artifact_versions")
    op.execute("DROP FUNCTION nexus_version_immutable()")
    op.drop_constraint("evaluation_status", "evaluations", type_="check")
    op.execute(
        "UPDATE evaluations SET status = CASE WHEN status='COMPLETED' THEN 'completed' "
        "WHEN status IN ('FAILED','CANCELLED','DESTROYED') THEN 'failed' "
        "WHEN status IN ('RUNNING','FINALIZING','PROVISIONING') THEN 'running' ELSE 'draft' END"
    )
    op.create_check_constraint(
        "evaluation_status",
        "evaluations",
        "status IN ('draft','queued','running','completed','failed')",
    )
    op.drop_constraint("execution_mode", "evaluations", type_="check")
    op.execute("UPDATE evaluations SET execution_mode='mock' WHERE execution_mode='local_mock'")
    op.create_check_constraint(
        "execution_mode", "evaluations", "execution_mode IN ('mock','production')"
    )
    op.drop_constraint("uq_event_sequence", "security_events", type_="unique")
    op.drop_column("security_events", "sequence")
    for name in (
        "event_sequence",
        "worker_claimed",
        "blue_approved",
        "manifest_digest",
        "manifest",
    ):
        op.drop_column("evaluations", name)
    for name in ("red_version_id", "blue_version_id", "model_version_id", "flow_policy_version_id"):
        op.drop_constraint(f"fk_evaluation_{name}", "evaluations", type_="foreignkey")
        op.drop_column("evaluations", name)
    op.drop_table("version_grants")
    op.drop_table("artifact_versions")
