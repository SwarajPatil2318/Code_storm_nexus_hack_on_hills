"""Explicit approved role/migration cutover; never invoked by API startup."""

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from nexus_api.db_roles import provision_roles
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def configure(config, env_path):
    engine = create_engine(config["admin_url"], hide_parameters=True)
    schema = config.get("schema", "public")
    try:
        provision_roles(engine, schema, config["roles"], config["passwords"])
        urls = {
            name: make_url(config["admin_url"])
            .set(username=role, password=config["passwords"][name])
            .render_as_string(hide_password=False)
            for name, role in config["roles"].items()
        }
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "apps/api",
            env={**os.environ, "NEXUS_MIGRATION_DATABASE_URL": urls["migrator"]},
            check=True,
        )
        provision_roles(engine, schema, config["roles"], config["passwords"])
        changes = {
            "NEXUS_DATABASE_URL": urls["api"],
            "NEXUS_MIGRATION_DATABASE_URL": urls["migrator"],
            "NEXUS_PROVISIONER_DATABASE_URL": urls["provisioner"],
        }
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        lines = [line for line in lines if line.partition("=")[0] not in changes]
        lines += [f"{key}={value}" for key, value in changes.items()]
        fd, temporary = tempfile.mkstemp(prefix=".env-cutover-", dir=env_path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write("\n".join(lines) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, env_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / "apps/api/.env")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if stat.S_IMODE(args.config.stat().st_mode) & 0o077:
        raise SystemExit("ROLE_CONFIG_REQUIRES_MODE_0600")
    if not args.apply:
        print(
            "Plan only: provision roles, migrate as schema owner, refresh grants, atomically update three connection settings. Back up/stop the old API and provisioner before applying to an existing installation."
        )
        return
    try:
        configure(json.loads(args.config.read_text()), args.env_file)
    except Exception:  # noqa: BLE001 - never expose credentials from administrative errors
        raise SystemExit(
            "DATABASE_CUTOVER_INCOMPLETE; inspect protected state; no credential fallback"
        ) from None
    print(
        "Database configured with separate migration/API/provisioner identities; no credentials printed"
    )


if __name__ == "__main__":
    main()
