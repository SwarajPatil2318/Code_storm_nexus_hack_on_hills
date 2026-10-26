"""Disposable same-host qualification; never run over retained installations.

Reuses existing migrations, builders, custody and process launchers. Each selected
qualification namespace refuses resources owned by another source copy. Model
artifacts are read-only inputs; no global cleanup or host setting changes.
"""

import argparse
import json
import os
import secrets
import socket
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

parser = argparse.ArgumentParser(
    description="Same-host disposable qualification using existing NEXUS launchers. Run only in a clean source copy."
)
parser.add_argument("action", choices=["setup", "start", "status", "stop"])
parser.add_argument(
    "--model-state",
    type=Path,
    required=True,
    help="Existing verified model-cache/inference-bin directory, used read-only",
)
parser.add_argument(
    "--instance", help="New disposable instance, never a retained profile"
)
parser.add_argument("--api-port", type=int)
parser.add_argument("--web-port", type=int)
parser.add_argument("--database-port", type=int)
args = parser.parse_args()
from scripts.qualification_profile import (
    qualification_profile,
    validate_qualification_path,
)

try:
    profile = qualification_profile(
        args.instance, args.api_port, args.web_port, args.database_port
    )
except ValueError as error:
    parser.error(str(error))
ROOT = Path.cwd().resolve()
if args.action in {"setup", "start"}:
    try:
        validate_qualification_path(ROOT)
    except ValueError as error:
        raise SystemExit(str(error)) from None
model_state = args.model_state.resolve()
if (ROOT / ".runtime/proof-demo").exists() or (
    ROOT / ".runtime/database-roles.secrets.json"
).exists():
    raise SystemExit("CLEAN_SOURCE_COPY_REQUIRED; retained installations are refused")
state = ROOT / ".runtime/ui-qa"
state.mkdir(mode=0o700, parents=True, exist_ok=True)
os.umask(0o077)
profile_file = state / "qualification-profile.json"
selected_profile = {**asdict(profile), "source": str(ROOT)}
if profile_file.exists() and json.loads(profile_file.read_bytes()) != selected_profile:
    raise SystemExit("QUALIFICATION_PROFILE_MISMATCH")
if (state / "database.secrets.json").exists():
    c = json.loads((state / "database.secrets.json").read_bytes())
    if (
        c["roles"].get("api") != profile.role_prefix + "_api"
        or f":{profile.database_port}/" not in c["admin_url"]
    ):
        raise SystemExit("QUALIFICATION_DATABASE_IDENTITY_MISMATCH")
if not profile_file.exists():
    profile_file.write_text(json.dumps(selected_profile))
os.environ.update(
    NEXUS_QA_PROFILE="ui",
    NEXUS_RUNTIME_STATE_DIR=str(state),
    NEXUS_MODEL_STATE_DIR=str(model_state),
    NEXUS_CONFIG_FILE=str(state / "api.env"),
)
from scripts import assurance_qa as q

q.STATE = state
q.SCOPE = profile.scope
q.API_PORT = profile.api_port
q.WEB_PORT = profile.web_port
q.baseline = lambda: None
q.select_instance()
q.demo.PROJECT = profile.project
q.demo.API_NAME = profile.project + "-api"
q.demo.SIGNER_NAME = profile.project + "-signer"
base = q.ORIGINAL_ENV


def env():
    values = base()
    values["NEXUS_MODEL_STATE_DIR"] = str(model_state)
    return values


q.ORIGINAL_ENV = env
if not (state / "owner").exists():
    q.demo.private("owner", str(uuid4()))
owner = (state / "owner").read_text().strip()
if not (state / "database.secrets.json").exists():
    pw = {
        k: secrets.token_hex(24)
        for k in ["bootstrap", "api", "migrator", "provisioner", "signer"]
    }
    schema = "public"
    q.demo.private(
        "database.secrets.json",
        {
            "admin_url": f"postgresql+psycopg://nexus_demo_bootstrap:{pw['bootstrap']}@127.0.0.1:{profile.database_port}/nexus_proof_demo",
            "schema": schema,
            "roles": {
                k: profile.role_prefix + "_" + k
                for k in ["api", "migrator", "provisioner"]
            },
            "passwords": pw,
        },
    )
    q.demo.private(
        "compose.env", f"POSTGRES_PASSWORD={pw['bootstrap']}\nDEMO_OWNER={owner}\n"
    )
compose = state / "compose.clean.yaml"
compose.write_text(
    (ROOT / "infrastructure/compose.demo.yaml")
    .read_text()
    .replace("127.0.0.1:55438:5432", f"127.0.0.1:{profile.database_port}:5432")
)


def docker(*args):
    return q.demo.run([*q.demo.D, *args], timeout=120)


def pg(*args):
    return docker(
        "compose",
        "--env-file",
        state / "compose.env",
        "-p",
        profile.project,
        "-f",
        compose,
        *args,
    )


# Validate existing ownership before any Compose operation; no shared resource
# may be adopted, restarted or overwritten by this qualification namespace.
for resource, kind, label in [
    (profile.project + "-postgres-1", "container", "demo-postgres"),
    (profile.project + "_demo_data", "volume", "demo-data"),
    (profile.project + "_default", "network", "demo-services"),
]:
    q.demo.assert_owned(resource, kind, label)
if args.action in {"setup", "start"}:
    if args.instance and not (state / "initialized").exists():
        # A new instance must not bind over a running service, even if its name is free.
        for port in (profile.api_port, profile.web_port, profile.database_port):
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError:
                    raise SystemExit("QUALIFICATION_PORT_OCCUPIED") from None
    pg("up", "-d", "--wait", "--wait-timeout", "90")
    q.initialize()
# QA initialization reuses the exact role/migration/custody/image builders, with
# an independently owned database, roles, keys and immutable image tags.
if args.action == "setup":
    q.demo.run(["npm", "run", "build"], timeout=360)
    (state / "clean-setup-result.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "same_host": True,
                "database_and_roles": "OWNED_QUALIFICATION_SCOPE",
                "signing_custody": "OWNED_QUALIFICATION_VOLUME",
                "dependency_installation": "EXTERNAL_PREREQUISITE",
                "production_build": True,
                "historical_archives": "NOT_IMPORTED",
                "source_release": "NOT_ASSERTED_BY_HELPER",
            }
        )
    )
    print(
        "Clean setup, migrations, distinct roles, signing custody, immutable images and frontend build PASS. Same host; no historical archives imported."
    )
elif args.action == "start":
    q.demo.launch(
        "provisioner",
        [sys.executable, "-m", "services.orchestrator.server"],
        lambda: (
            (state / "control/provisioner.sock").exists()
            and "Trusted provisioner ready" in (state / "provisioner.log").read_text()
        ),
    )
    q.demo.launch(
        "signer",
        [
            sys.executable,
            ROOT / "scripts/run_signer.py",
            "--config",
            state / "signer.secrets.json",
            "--name",
            q.demo.SIGNER_NAME,
            "--compose-project",
            profile.project,
        ],
        lambda: (
            "Restricted evidence signer ready" in (state / "signer.log").read_text()
        ),
    )
    q.demo.launch(
        "api",
        [
            sys.executable,
            ROOT / "scripts/run_confined_api.py",
            "--port",
            str(profile.api_port),
            "--name",
            q.demo.API_NAME,
            "--compose-project",
            profile.project,
        ],
        lambda: q.demo.http_ready(q.demo.API + "/ready"),
    )
    q.demo.launch(
        "web",
        [
            ROOT / "node_modules/.bin/next",
            "start",
            ROOT / "apps/web",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(profile.web_port),
        ],
        lambda: q.demo.http_ready(q.demo.WEB + "/login"),
    )
    print(
        f"Clean services ready at loopback {profile.web_port}/{profile.api_port}, PostgreSQL {profile.database_port}."
    )
elif args.action == "status":
    result = {
        "same_host": True,
        "api_ready": q.demo.http_ready(q.demo.API + "/ready"),
        "frontend_ready": q.demo.http_ready(q.demo.WEB + "/login"),
        "inference": "NOT_RUN_BY_STATUS",
    }
    print(json.dumps(result))
    if not result["api_ready"] or not result["frontend_ready"]:
        raise SystemExit(1)
elif args.action == "stop":
    from sqlalchemy import create_engine, text

    c = q.demo.read("database.secrets.json")
    e = create_engine(c["admin_url"], hide_parameters=True)
    with e.connect() as db:
        active = db.scalar(
            text(
                "SELECT count(*) FROM evaluations WHERE status IN ('PROVISIONING','RUNNING','FINALIZING')"
            )
        )
        if active:
            raise SystemExit("ACTIVE_QUALIFICATION_EVALUATION_WAIT_FOR_CLEANUP")
    e.dispose()
    q.stop_services()
    pg("stop")
    print(
        "Stopped only owned clean services and PostgreSQL; volumes, keys and history retained."
    )
