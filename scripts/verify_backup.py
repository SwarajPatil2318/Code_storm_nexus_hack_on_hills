"""Read-only backup comparison: strict catalogue, every table and artifact bytes.

Capture while admissions/services are quiescent, or import the same exported
snapshot used by pg_dump. Baselines contain private schema/data fingerprints.
No restore, migration, role change or service operation is performed here.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text

from scripts.schema_verification import catalog_snapshot, compare


def data_snapshot(db, schema="public"):
    quote = db.dialect.identifier_preparer.quote
    tables = (
        db.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname=:schema ORDER BY tablename"
            ),
            {"schema": schema},
        )
        .scalars()
        .all()
    )
    fingerprints = {}
    for table in tables:
        rows = (
            db.execute(
                text(f"SELECT row_to_json(t) FROM {quote(schema)}.{quote(table)} t")
            )
            .scalars()
            .all()
        )
        # Same full-row canonicalization as the original halted preflight.
        canonical = json.dumps(
            sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, default=str)),
            sort_keys=True,
            default=str,
        ).encode()
        fingerprints[table] = {
            "count": len(rows),
            "sha256": hashlib.sha256(canonical).hexdigest(),
        }
    if not {"alembic_version", "artifact_versions", "users", "evaluations"} <= set(
        tables
    ):
        raise ValueError("REQUIRED_NEXUS_TABLES_MISSING")
    artifacts = 0
    for row in db.execute(
        text(f"SELECT data,sha256,byte_size FROM {quote(schema)}.artifact_versions")
    ):
        if (
            len(row.data) != row.byte_size
            or hashlib.sha256(row.data).hexdigest() != row.sha256
        ):
            raise ValueError("ARTIFACT_INTEGRITY")
        artifacts += 1
    return {
        "tables": fingerprints,
        "revision": db.scalar(
            text(f"SELECT version_num FROM {quote(schema)}.alembic_version")
        ),
        "artifact_versions_verified": artifacts,
    }


def capture(url, schema="public", snapshot=None):
    engine = create_engine(
        url,
        hide_parameters=True,
        isolation_level="REPEATABLE READ",
        connect_args={"options": "-c default_transaction_read_only=on -c timezone=UTC"},
    )
    try:
        with engine.connect() as db:
            if snapshot:
                # PostgreSQL does not accept a bind parameter in this grammar.
                # Its exported identifiers contain only hexadecimal digits and '-'.
                if not snapshot or any(
                    c not in "0123456789ABCDEFabcdef-" for c in snapshot
                ):
                    raise ValueError("SNAPSHOT_IDENTIFIER")
                db.execute(text("SET TRANSACTION SNAPSHOT '" + snapshot + "'"))
            return {
                "catalog": catalog_snapshot(db, schema),
                "data": data_snapshot(db, schema),
            }
    finally:
        engine.dispose()


def verify(source, restored):
    result = compare(source["catalog"], restored["catalog"])
    if source["data"] != restored["data"]:
        raise ValueError("BACKUP_DATA_MISMATCH")
    return {
        **result,
        "tables_verified": len(source["data"]["tables"]),
        "artifact_versions_verified": source["data"]["artifact_versions_verified"],
        "revision": source["data"]["revision"],
    }


def private_read(path):
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("PRIVATE_FILE_REQUIRED")
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["capture", "compare"])
    parser.add_argument(
        "--config", type=Path, required=True, help="0600 JSON: database_url, schema"
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument(
        "--snapshot", help="Capture only; import pg_dump's still-held snapshot"
    )
    args = parser.parse_args()
    config = private_read(args.config)
    if args.action == "compare" and args.snapshot:
        raise ValueError("SNAPSHOT_CAPTURE_ONLY")
    observed = capture(
        config["database_url"], config.get("schema", "public"), args.snapshot
    )
    if args.action == "capture":
        fd = os.open(
            args.baseline, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "w") as file:
            json.dump(observed, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        print("Private baseline captured; no database changes")
    else:
        print(json.dumps(verify(private_read(args.baseline), observed)))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - private connection/data diagnostics
        raise SystemExit("BACKUP_VERIFICATION_FAILED:" + type(error).__name__) from None
