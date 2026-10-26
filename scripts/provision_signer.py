"""Administrator-only bounded signer role setup for a selected dedicated database."""

import argparse
import json
import re
from pathlib import Path

from psycopg import sql
from sqlalchemy import create_engine


def provision(engine, schema, name, password):
    if (
        any(not re.fullmatch("[a-z][a-z0-9_]{0,62}", v) for v in [schema, name])
        or len(password) < 32
    ):
        raise ValueError("SIGNER_ROLE_CONFIG")
    with engine.begin() as connection:
        c = connection.connection.driver_connection.cursor()
        c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,))
        if c.fetchone():
            raise ValueError("NEW_SIGNER_IDENTITY_REQUIRED")
        c.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(name), sql.Literal(password))
        )
        c.execute("SELECT current_database()")
        database = c.fetchone()[0]
        c.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(name)
            )
        )
        c.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(name)
            )
        )
        c.execute(
            sql.SQL("ALTER ROLE {} IN DATABASE {} SET search_path TO {}").format(
                sql.Identifier(name), sql.Identifier(database), sql.Identifier(schema)
            )
        )
        reads = [
            "evaluations",
            "evaluation_memberships",
            "artifact_versions",
            "security_events",
            "case_records",
            "evaluation_results",
            "runtime_records",
            "evaluation_jobs",
            "comparisons",
            "alembic_version",
            "evidence_snapshots",
            "evidence_receipts",
            "evidence_requests",
            "evidence_keys",
        ]
        c.execute(
            sql.SQL("GRANT SELECT (id, role, is_active) ON {} TO {}").format(
                sql.Identifier(schema, "users"), sql.Identifier(name)
            )
        )
        for table in reads:
            c.execute(
                sql.SQL("GRANT SELECT ON {} TO {}").format(
                    sql.Identifier(schema, table), sql.Identifier(name)
                )
            )
        for table in ["evidence_snapshots", "evidence_receipts", "evidence_keys"]:
            c.execute(
                sql.SQL("GRANT INSERT ON {} TO {}").format(
                    sql.Identifier(schema, table), sql.Identifier(name)
                )
            )
        c.execute(
            sql.SQL("GRANT UPDATE (state, reason_code, receipt_id) ON {} TO {}").format(
                sql.Identifier(schema, "evidence_requests"), sql.Identifier(name)
            )
        )
        c.execute(
            sql.SQL("GRANT UPDATE (event_sequence) ON {} TO {}").format(
                sql.Identifier(schema, "evaluations"), sql.Identifier(name)
            )
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    if a.config.is_symlink() or a.config.stat().st_mode & 0o077:
        raise SystemExit("PRIVATE_CONFIG_REQUIRED")
    if not a.apply:
        print(
            "Plan only: create a new signer identity with selected reads and evidence-only writes; no API key access or runtime administrator fallback"
        )
        return
    try:
        d = json.loads(a.config.read_text())
        e = create_engine(d["admin_url"], hide_parameters=True)
        try:
            provision(e, d.get("schema", "public"), d["role"], d["password"])
        finally:
            e.dispose()
    except Exception:  # noqa: BLE001 - suppress private failure values
        raise SystemExit(
            "SIGNER_ROLE_SETUP_FAILED; private values suppressed"
        ) from None
    print("Restricted signer identity provisioned; no credentials printed")


if __name__ == "__main__":
    main()
