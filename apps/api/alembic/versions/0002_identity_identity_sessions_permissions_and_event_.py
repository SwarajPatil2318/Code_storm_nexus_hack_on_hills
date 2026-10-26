"""identity sessions permissions and event visibility

Revision ID: 0002_identity
Revises: 0001_foundation
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_identity"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("user_role", "users", type_="check")
    op.execute(
        "UPDATE users SET role = CASE role WHEN 'red' THEN 'RED_OPERATOR' "
        "WHEN 'blue' THEN 'BLUE_OPERATOR' WHEN 'auditor' THEN 'AUDITOR' "
        "WHEN 'admin' THEN 'ADMIN' ELSE role END"
    )
    op.create_check_constraint(
        "user_role", "users", "role IN ('RED_OPERATOR', 'BLUE_OPERATOR', 'AUDITOR', 'ADMIN')"
    )
    op.create_table(
        "login_throttles",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "auth_audit",
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_auth_audit_actor_id"), "auth_audit", ["actor_id"], unique=False)
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_auth_sessions_expires_at"), "auth_sessions", ["expires_at"], unique=False
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.create_table(
        "evaluation_memberships",
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["evaluations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("evaluation_id", "user_id"),
    )
    op.add_column("artifacts", sa.Column("private_content", sa.Text(), nullable=True))
    op.add_column("evaluations", sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "security_events",
        sa.Column("source", sa.String(length=40), server_default="API", nullable=False),
    )
    op.add_column(
        "security_events",
        sa.Column("destination", sa.String(length=40), server_default="API", nullable=False),
    )
    op.add_column(
        "security_events",
        sa.Column(
            "visibility", sa.String(length=40), server_default="EVALUATION_METADATA", nullable=False
        ),
    )
    op.add_column("security_events", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.add_column("security_events", sa.Column("subject_user_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE security_events SET correlation_id = id")
    op.alter_column("security_events", "correlation_id", nullable=False)
    op.create_foreign_key(
        "fk_security_events_subject_user_id",
        "security_events",
        "users",
        ["subject_user_id"],
        ["id"],
    )
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False)
    )
    op.add_column(
        "users", sa.Column("is_demo", sa.Boolean(), server_default="false", nullable=False)
    )


def downgrade():
    op.drop_constraint("user_role", "users", type_="check")
    op.execute(
        "UPDATE users SET role = CASE role WHEN 'RED_OPERATOR' THEN 'red' "
        "WHEN 'BLUE_OPERATOR' THEN 'blue' WHEN 'AUDITOR' THEN 'auditor' "
        "WHEN 'ADMIN' THEN 'admin' ELSE role END"
    )
    op.create_check_constraint("user_role", "users", "role IN ('red', 'blue', 'auditor', 'admin')")
    op.drop_column("users", "is_demo")
    op.drop_column("users", "is_active")
    op.drop_column("users", "password_hash")
    op.drop_constraint("fk_security_events_subject_user_id", "security_events", type_="foreignkey")
    op.drop_column("security_events", "subject_user_id")
    op.drop_column("security_events", "correlation_id")
    op.drop_column("security_events", "visibility")
    op.drop_column("security_events", "destination")
    op.drop_column("security_events", "source")
    op.drop_column("evaluations", "sealed_at")
    op.drop_column("artifacts", "private_content")
    op.drop_table("evaluation_memberships")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_expires_at"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index(op.f("ix_auth_audit_actor_id"), table_name="auth_audit")
    op.drop_table("auth_audit")
    op.drop_table("login_throttles")
