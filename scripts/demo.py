"""Persistent loopback M8 demo; wraps existing launchers, never the normal installation.

No reset/delete-volume operation. Only this demo's recorded processes and labelled
Compose services are stopped. Database and signing key survive stop/start.
"""

import argparse
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from nexus_api.auth import DEMO_IDENTITIES, hasher
from nexus_api.models import User
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from scripts.configure_database import configure
from scripts.proof_custody import create, operation, volume_info
from scripts.provision_signer import provision
from scripts.verify_backup import capture

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".runtime/proof-demo"
PROJECT = "nexus-m8-demo"
API_NAME = PROJECT + "-api"
SIGNER_NAME = PROJECT + "-signer"
KEY_VOLUME = PROJECT + "-signing-key"
API = "http://127.0.0.1:8008"
WEB = "http://127.0.0.1:3008"
D = ["docker", "--host", "unix:///var/run/docker.sock"]


def private(path, value):
    path = STATE / path
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(
            value if isinstance(value, str) else json.dumps(value, indent=2) + "\n"
        )


def read(name):
    return json.loads((STATE / name).read_text())


def env():
    # Do not inherit normal database/control credentials from an operator shell.
    values = {k: v for k, v in os.environ.items() if not k.startswith("NEXUS_")}
    return {
        **values,
        "PYTHONPATH": f"{ROOT / 'apps/api'}:{ROOT}",
        "NEXUS_RUNTIME_STATE_DIR": str(STATE),
        "NEXUS_MODEL_STATE_DIR": str(ROOT / ".runtime"),
        "NEXUS_CONFIG_FILE": str(STATE / "api.env"),
        "NEXUS_DEMO_WEB": "1",
        "NEXT_PUBLIC_API_URL": API,
        "NEXUS_API_INTERNAL_URL": API,
        "NODE_OPTIONS": "--max-old-space-size=1536",
    }


def run(args, *, timeout=120, capture_output=False):
    return subprocess.run(
        [str(v) for v in args],
        cwd=ROOT,
        env=env(),
        check=True,
        timeout=timeout,
        capture_output=capture_output,
        text=True,
    )


def compose(*args):
    return run(
        [
            *D,
            "compose",
            "--env-file",
            STATE / "compose.env",
            "-p",
            PROJECT,
            "-f",
            ROOT / "infrastructure/compose.demo.yaml",
            *args,
        ]
    )


def check_resources():
    available = int(
        next(
            line.split()[1]
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemAvailable:")
        )
    )
    if available < 3 * 1024 * 1024:
        raise ValueError("DEMO_NEEDS_3_GIB_AVAILABLE_RAM")
    if os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize < 3 * 1024**3:
        raise ValueError("DEMO_NEEDS_3_GIB_FREE_DISK")
    for port in [3008, 8008, 55438]:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                if port != 55438:
                    raise
                assert_owned(
                    PROJECT + "-postgres-1", "container", "demo-postgres", required=True
                )
    if not shutil.which("setfacl"):
        raise ValueError("SIGNER_POSIX_ACL_TOOL_REQUIRED")
    run([*D, "info", "--format", "{{.CgroupVersion}}"], capture_output=True)


def assert_owned(name, kind, expected_kind, *, required=False):
    result = subprocess.run(
        [*D, kind, "inspect", name], capture_output=True, check=False, timeout=15
    )
    if result.returncode:
        if required:
            raise ValueError("DEMO_RESOURCE_UNAVAILABLE:" + name)
        return
    item = json.loads(result.stdout)[0]
    labels = (
        item["Config"].get("Labels", {})
        if kind == "container"
        else item.get("Labels", {})
    )
    owner_file = STATE / "owner"
    if (
        not owner_file.exists()
        or labels.get("io.nexus.owner") != owner_file.read_text().strip()
        or labels.get("io.nexus.kind") != expected_kind
    ):
        raise ValueError("DEMO_RESOURCE_OWNER_MISMATCH:" + name)


def validate_resources():
    for name, kind, label in [
        (PROJECT + "-postgres-1", "container", "demo-postgres"),
        (PROJECT + "_demo_data", "volume", "demo-data"),
        (PROJECT + "_default", "network", "demo-services"),
        (API_NAME, "container", "public-api"),
        (SIGNER_NAME, "container", "proof-signer"),
        (KEY_VOLUME, "volume", "proof-key"),
    ]:
        assert_owned(name, kind, label)


def normal_snapshot():
    url = dotenv_values(ROOT / "apps/api/.env")["NEXUS_DATABASE_URL"]
    db = capture(url)
    claims = {}
    for path in sorted((ROOT / ".runtime/job-locks").glob("*.lock")):
        stat = path.stat()
        claims[path.name] = [
            stat.st_ino,
            stat.st_uid,
            stat.st_gid,
            stat.st_mode,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        ]
    files = {}
    for path in [
        ROOT / "apps/api/.env",
        ROOT / "apps/api/.env.demo.local",
        ROOT / "apps/web/.env.local",
        ROOT / ".runtime/owner",
        ROOT / ".runtime/control.key",
        ROOT / ".runtime/images.json",
        ROOT / ".runtime/api-image",
        ROOT / ".runtime/model-runtime.json",
    ]:
        if path.exists():
            files[str(path.relative_to(ROOT))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    containers = {}
    for name in ["nexus-public-api-m4", "nexus-postgres-1"]:
        item = json.loads(run([*D, "inspect", name], capture_output=True).stdout)[0]
        containers[name] = {"id": item["Id"], "started_at": item["State"]["StartedAt"]}
    return {"database": db, "claims": claims, "files": files, "containers": containers}


def initialize():
    if (STATE / "initialized").exists():
        return
    if not (STATE / "owner").exists():
        private("owner", str(uuid4()))
    owner = (STATE / "owner").read_text().strip()
    if not (STATE / "database.secrets.json").exists():
        passwords = {
            k: secrets.token_hex(24)
            for k in ["bootstrap", "api", "migrator", "provisioner", "signer"]
        }
        admin = f"postgresql+psycopg://nexus_demo_bootstrap:{passwords['bootstrap']}@127.0.0.1:55438/nexus_proof_demo"
        private(
            "database.secrets.json",
            {
                "admin_url": admin,
                "schema": "public",
                "roles": {
                    k: "nexus_demo_" + k for k in ["api", "migrator", "provisioner"]
                },
                "passwords": passwords,
            },
        )
        private(
            "compose.env",
            f"POSTGRES_PASSWORD={passwords['bootstrap']}\nDEMO_OWNER={owner}\n",
        )
    if not (STATE / "normal-before.json").exists():
        private("normal-before.json", normal_snapshot())
    for name in ["images.json"]:
        if not (STATE / name).exists():
            private(name, (ROOT / ".runtime" / name).read_text())
    if not (STATE / "api-image").exists():
        run(
            [
                sys.executable,
                ROOT / "scripts/build_api_image.py",
                "--tag",
                PROJECT + "-api:m8",
            ],
            timeout=600,
        )
    compose("up", "-d", "--wait", "--wait-timeout", "90")
    config = read("database.secrets.json")
    configure(config, STATE / "api.env")
    admin = create_engine(config["admin_url"], hide_parameters=True)
    try:
        with admin.connect() as connection:
            signer_exists = connection.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='nexus_demo_signer')"
                )
            )
        if not signer_exists:
            provision(
                admin, "public", "nexus_demo_signer", config["passwords"]["signer"]
            )
    finally:
        admin.dispose()
    # Build signer code against the selected immutable API image, no key in context.
    run(
        [
            sys.executable,
            ROOT / "scripts/build_signer_image.py",
            "--tag",
            PROJECT + "-signer:m8",
        ],
        timeout=180,
    )
    image = (STATE / "signer-image").read_text().strip()
    if not (STATE / "trust.json").exists():
        create(KEY_VOLUME, image, owner)
        public = operation(KEY_VOLUME, image, {"action": "generate"}, writable=True)
        private(
            "trust.json",
            {
                public["key_id"]: {
                    k: public[k] for k in ["public_key", "activated_at", "retired_at"]
                }
            },
        )
        private("signer-public.json", public)
    ring = read("trust.json")
    volume_info(KEY_VOLUME, owner)
    operation(
        KEY_VOLUME, image, {"action": "selftest", "expected_key_id": next(iter(ring))}
    )
    signer_url = (
        make_url(config["admin_url"])
        .set(username="nexus_demo_signer", password=config["passwords"]["signer"])
        .render_as_string(hide_password=False)
    )
    private(
        "signer.secrets.json",
        {"database_url": signer_url, "key_volume": KEY_VOLUME, "trusted_keys": ring},
    )
    with (STATE / "api.env").open("a") as file:
        file.write("NEXUS_DEMO_AUTH_ENABLED=true\nNEXUS_ENVIRONMENT=development\n")
        file.write("NEXUS_CORS_ORIGINS='" + json.dumps([WEB]) + "'\n")
        file.write("NEXUS_PROOF_TRUSTED_KEYS='" + json.dumps(ring) + "'\n")
    credentials_path = STATE / "credentials.env"
    if not credentials_path.exists():
        private(
            "credentials.env",
            "# Disposable DEVELOPMENT/DEMO identities only.\n"
            + "".join(
                f"NEXUS_DEMO_{role}_PASSWORD={secrets.token_urlsafe(24)}\n"
                for role in ["RED", "BLUE", "AUDITOR", "ADMIN"]
            ),
        )
    credentials = dotenv_values(credentials_path)
    api_url = dotenv_values(STATE / "api.env")["NEXUS_DATABASE_URL"]
    engine = create_engine(api_url, hide_parameters=True)
    try:
        with Session(engine) as db:
            for identity, role in zip(
                DEMO_IDENTITIES, ["RED", "BLUE", "AUDITOR", "ADMIN"], strict=True
            ):
                if db.scalar(select(User).where(User.email == identity.email)) is None:
                    db.add(
                        User(
                            email=identity.email,
                            display_name=identity.display_name,
                            role=identity.role.value,
                            is_demo=True,
                            password_hash=hasher.hash(
                                credentials[f"NEXUS_DEMO_{role}_PASSWORD"]
                            ),
                        )
                    )
            db.commit()
    finally:
        engine.dispose()
    private("initialized", "0008_proof_vault\n")


def process_identity(pid):
    try:
        # Include kernel start ticks to reject reused PIDs. Do not signal by name.
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":
            return None
        return stat[19]
    except FileNotFoundError:
        return None


def launch(name, args, ready):
    path = STATE / f"{name}.process.json"
    if path.exists():
        old = read(path.name)
        if process_identity(old["pid"]) == old["start"]:
            if ready():
                return
            raise ValueError("OWNED_PROCESS_RUNNING_BUT_NOT_READY:" + name)
    with (STATE / f"{name}.log").open("w") as log:
        proc = subprocess.Popen(
            [str(v) for v in args],
            cwd=ROOT,
            env=env(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    private(path.name, {"pid": proc.pid, "start": process_identity(proc.pid)})
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise ValueError("DEMO_PROCESS_EXITED:" + name)
        if ready():
            return
        time.sleep(0.5)
    raise ValueError("DEMO_READY_DEADLINE:" + name)


def http_ready(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status == 200
    except OSError:
        return False


def start():
    validate_resources()
    if http_ready(API + "/ready"):
        status()
        return
    check_resources()
    initialize()
    compose("up", "-d", "--wait", "--wait-timeout", "90")
    # Only build this separate frontend once. Stop/start reuses it.
    if not (ROOT / "apps/web/.next-demo/BUILD_ID").exists():
        run(["npm", "run", "build"], timeout=300)
    launch(
        "provisioner",
        [sys.executable, "-m", "services.orchestrator.server"],
        lambda: (
            (STATE / "control/provisioner.sock").exists()
            and "Trusted provisioner ready" in (STATE / "provisioner.log").read_text()
        ),
    )
    launch(
        "signer",
        [
            sys.executable,
            ROOT / "scripts/run_signer.py",
            "--config",
            STATE / "signer.secrets.json",
            "--name",
            SIGNER_NAME,
            "--compose-project",
            PROJECT,
        ],
        lambda: (
            "Restricted evidence signer ready" in (STATE / "signer.log").read_text()
        ),
    )
    launch(
        "api",
        [
            sys.executable,
            ROOT / "scripts/run_confined_api.py",
            "--port",
            "8008",
            "--name",
            API_NAME,
            "--compose-project",
            PROJECT,
        ],
        lambda: http_ready(API + "/ready"),
    )
    launch(
        "web",
        [
            ROOT / "node_modules/.bin/next",
            "start",
            ROOT / "apps/web",
            "--hostname",
            "127.0.0.1",
            "--port",
            "3008",
        ],
        lambda: http_ready(WEB + "/login"),
    )
    status()


def status():
    config = read("database.secrets.json")
    engine = create_engine(
        make_url(config["admin_url"]).set(
            username="nexus_demo_api", password=config["passwords"]["api"]
        ),
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
    )
    try:
        with engine.connect() as c:
            revision = c.scalar(text("SELECT version_num FROM alembic_version"))
            counts = {
                t: c.scalar(text(f"SELECT count(*) FROM {t}"))
                for t in ["evaluations", "evidence_receipts"]
            }
    finally:
        engine.dispose()
    processes = {}
    for name in ["provisioner", "signer", "api", "web"]:
        path = STATE / f"{name}.process.json"
        item = read(path.name) if path.exists() else None
        processes[name] = bool(item and process_identity(item["pid"]) == item["start"])
    result = {
        "mode": "DEVELOPMENT/DEMO",
        "web": WEB,
        "api": API,
        "postgres": "127.0.0.1:55438",
        "revision": revision,
        "api_ready": http_ready(API + "/ready"),
        "web_ready": http_ready(WEB + "/login"),
        "processes": processes,
        **counts,
        "key_id": next(iter(read("trust.json"))),
    }
    print(json.dumps(result, indent=2))
    if (
        revision != "0008_proof_vault"
        or not all(processes.values())
        or not result["api_ready"]
        or not result["web_ready"]
    ):
        raise ValueError("DEMO_NOT_READY")


def stop():
    if not (STATE / "compose.env").exists():
        return
    config = read("database.secrets.json")
    engine = create_engine(
        config["admin_url"], hide_parameters=True, connect_args={"connect_timeout": 3}
    )
    try:
        with engine.connect() as c:
            active = c.scalar(
                text(
                    "SELECT count(*) FROM evaluations WHERE status IN ('PROVISIONING','RUNNING','FINALIZING')"
                )
            )
            if active:
                raise ValueError("ACTIVE_DEMO_EVALUATION; wait for verified cleanup")
    finally:
        engine.dispose()
    for name in ["web", "api", "signer", "provisioner"]:
        path = STATE / f"{name}.process.json"
        if not path.exists():
            continue
        item = read(path.name)
        if process_identity(item["pid"]) == item["start"]:
            os.kill(item["pid"], signal.SIGTERM)
            deadline = time.monotonic() + 45
            while process_identity(item["pid"]) == item["start"]:
                if time.monotonic() > deadline:
                    raise ValueError("GRACEFUL_STOP_UNVERIFIED:" + name)
                time.sleep(0.2)
        path.unlink()
    owner = (STATE / "owner").read_text().strip()
    for name in [API_NAME, SIGNER_NAME]:
        found = subprocess.run(
            [*D, "inspect", name], capture_output=True, check=False, timeout=15
        )
        if found.returncode == 0:
            raise ValueError("DEMO_CONTAINER_STOP_UNVERIFIED:" + name)
    # Verify exact ownership before Compose touches its selected database.
    item = json.loads(
        run([*D, "inspect", PROJECT + "-postgres-1"], capture_output=True).stdout
    )[0]
    if item["Config"]["Labels"].get("io.nexus.owner") != owner:
        raise ValueError("DEMO_DATABASE_OWNER_MISMATCH")
    compose("stop", "--timeout", "30")
    print(
        "Demo stopped gracefully; database, history, receipts, trust and signing key retained"
    )


def preservation():
    before, after = read("normal-before.json"), normal_snapshot()
    # Sessions/login throttles may change under unrelated normal-app use; report
    # every table separately rather than silently excluding those records.
    result = {
        "unchanged": before == after,
        "normal_revision": after["database"]["data"]["revision"],
        "claims_unchanged": before["claims"] == after["claims"],
        "claim_count": len(after["claims"]),
        "config_unchanged": before["files"] == after["files"],
        "services_not_restarted": before["containers"] == after["containers"],
        "database_unchanged": before["database"] == after["database"],
    }
    private("preservation.json", result)
    print(json.dumps(result, indent=2))
    if not result["unchanged"]:
        raise ValueError("NORMAL_INSTALLATION_DIFFERENCE_REQUIRES_REVIEW")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["start", "status", "stop", "verify", "preservation"]
    )
    args = parser.parse_args()
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / "operator.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "verify":
            run([sys.executable, ROOT / "scripts/demo_verify.py"], timeout=300)
        else:
            globals()[args.action]()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - do not print secret-bearing SQL or subprocess details
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        raise SystemExit("DEMO_FAILED:" + detail) from None
