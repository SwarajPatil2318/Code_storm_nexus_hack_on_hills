"""Explicit administrator operation for a dedicated NEXUS database, never API startup."""

import re

from psycopg import sql

from nexus_api import models  # noqa: F401 - register the exact allowed schema
from nexus_api.database import Base


def provision_roles(engine, schema, roles, passwords):
    """Transfer only the selected NEXUS schema; caller must approve live cutover.

    Roles must be new or already restricted and have no memberships. Password
    values are never returned; SQL is sent through a raw cursor, not logged.
    """
    if set(roles) != {"migrator", "api", "provisioner"} or len(set(roles.values())) != 3:
        raise ValueError("Three distinct database identities required")
    if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value) for value in [schema, *roles.values()]):
        raise ValueError("Invalid database identifier")
    if any(len(passwords[k]) < 32 for k in roles):
        raise ValueError("Provision independently generated credentials")
    with engine.begin() as connection:
        cursor = connection.connection.driver_connection.cursor()
        cursor.execute("SELECT current_database()")
        database = cursor.fetchone()[0]
        for kind, name in roles.items():
            cursor.execute(
                "SELECT oid, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
                "FROM pg_roles WHERE rolname=%s",
                (name,),
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=%s)", (existing[0],)
                )
                if any(existing[1:]) or cursor.fetchone()[0]:
                    raise ValueError("Existing role has unsafe authority; use a new identity")
            else:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOINHERIT NOBYPASSRLS"
                    ).format(sql.Identifier(name))
                )
            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(name), sql.Literal(passwords[kind])
                )
            )
        cursor.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}").format(
                sql.Identifier(schema), sql.Identifier(roles["migrator"])
            )
        )
        cursor.execute(
            sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(
                sql.Identifier(schema), sql.Identifier(roles["migrator"])
            )
        )
        cursor.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
        )
        cursor.execute(
            sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(schema))
        )
        if schema != "public":
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        for name in roles.values():
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database), sql.Identifier(name)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(name)
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} IN DATABASE {} SET search_path TO {}").format(
                    sql.Identifier(name), sql.Identifier(database), sql.Identifier(schema)
                )
            )
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s", (schema,))
        tables = {row[0] for row in cursor.fetchall()}
        if tables - (set(Base.metadata.tables) | {"alembic_version"}):
            raise ValueError(
                "Selected schema includes unrelated tables; refusing ownership transfer"
            )
        append_only = {
            "artifact_versions",
            "comparisons",
            "case_records",
            "security_events",
            "evaluation_results",
            "auth_audit",
            "evidence_requests",
            "evidence_verifications",
            "evidence_exports",
        }
        provisioner_reads = {
            "users",
            "evaluations",
            "artifact_versions",
            "runtime_records",
            "evaluation_jobs",
            "case_records",
            "evaluation_results",
            "comparisons",
            "alembic_version",
        }
        provisioner_writes = {
            "evaluations",
            "runtime_records",
            "evaluation_jobs",
            "case_records",
            "evaluation_results",
            "security_events",
        }
        for table in tables:
            target = sql.Identifier(schema, table)
            cursor.execute(
                sql.SQL("ALTER TABLE {} OWNER TO {}").format(
                    target, sql.Identifier(roles["migrator"])
                )
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON TABLE {} FROM PUBLIC, {}, {}").format(
                    target, sql.Identifier(roles["api"]), sql.Identifier(roles["provisioner"])
                )
            )
            if table == "evidence_snapshots":
                continue
            api_grant = (
                "SELECT"
                if table in {"alembic_version", "evidence_receipts", "evidence_keys"}
                else "SELECT, INSERT"
                if table in append_only
                else "SELECT, INSERT, UPDATE, DELETE"
            )
            cursor.execute(
                sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                    sql.SQL(api_grant), target, sql.Identifier(roles["api"])
                )
            )
            if table in provisioner_reads | provisioner_writes:
                grant = (
                    "SELECT, INSERT"
                    if table in append_only
                    else "SELECT, INSERT, UPDATE"
                    if table in provisioner_writes
                    else "SELECT"
                )
                cursor.execute(
                    sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                        sql.SQL(grant), target, sql.Identifier(roles["provisioner"])
                    )
                )
        for function in [
            "nexus_version_immutable",
            "nexus_sealed_binding",
            "immutable_campaign_record",
            "nexus_proof_immutable",
            "nexus_proof_prefix",
            "nexus_proof_epoch",
        ]:
            cursor.execute(
                "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname=%s AND p.proname=%s",
                (schema, function),
            )
            if cursor.fetchone():
                cursor.execute(
                    sql.SQL("ALTER FUNCTION {}() OWNER TO {}").format(
                        sql.Identifier(schema, function), sql.Identifier(roles["migrator"])
                    )
                )
        cursor.close()
