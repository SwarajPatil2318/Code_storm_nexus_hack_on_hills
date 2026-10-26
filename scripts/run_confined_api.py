"""Trusted development launcher; the resulting public API process has no Docker access."""

import argparse
import json
import signal
import subprocess
import time
from pathlib import Path

from nexus_api.config import Settings
from sqlalchemy.engine import make_url

from services.orchestrator.engine import CONFIG_FILE, STATE
from services.orchestrator.host_profile import name as host_name
from services.orchestrator.host_profile import port as host_port

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=host_port, default=8000)
parser.add_argument("--name", type=host_name, default="nexus-public-api-m4")
parser.add_argument("--compose-project", type=host_name, default="nexus")
host = parser.parse_args()

ROOT = Path(__file__).resolve().parents[1]
settings = Settings(_env_file=CONFIG_FILE)
state = STATE
image = (state / "api-image").read_text().strip()
if not image.startswith("sha256:") or len(image) != 71:
    raise SystemExit("Build the confined API image first")
if not (state / "control/provisioner.sock").exists():
    raise SystemExit("Start the trusted provisioner first")
ids = subprocess.check_output(
    [
        "docker",
        "--host",
        "unix:///var/run/docker.sock",
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.compose.project={host.compose_project}",
        "--filter",
        "label=com.docker.compose.service=postgres",
    ],
    text=True,
).split()
if len(ids) != 1:
    raise SystemExit("Exactly one local NEXUS PostgreSQL container is required")
postgres = json.loads(
    subprocess.check_output(
        ["docker", "--host", "unix:///var/run/docker.sock", "inspect", ids[0]],
        text=True,
    )
)[0]
network = next(iter(postgres["NetworkSettings"]["Networks"]))
config = settings.model_dump(mode="json")
config["database_url"] = (
    make_url(settings.database_url.get_secret_value())
    .set(host="postgres", port=5432)
    .render_as_string(hide_password=False)
)
config["provisioner_socket"] = "/run/nexus-control/provisioner.sock"
config["provisioner_key"] = (state / "control.key").read_text().strip()
name = host.name
owner = (state / "owner").read_text().strip()
existing = subprocess.run(
    ["docker", "--host", "unix:///var/run/docker.sock", "inspect", name],
    capture_output=True,
    check=False,
)
if existing.returncode == 0:
    inspected = json.loads(existing.stdout)[0]
    labels = inspected["Config"].get("Labels", {})
    if (
        labels.get("io.nexus.kind") != "public-api"
        or labels.get("io.nexus.owner") != owner
    ):
        raise SystemExit(
            "Refusing to remove an unrelated container with the reserved API name"
        )
    if inspected["State"].get("Running"):
        raise SystemExit("OWNED_API_ALREADY_RUNNING; existing service preserved")
    subprocess.run(
        ["docker", "--host", "unix:///var/run/docker.sock", "rm", "-f", name],
        check=True,
        stdout=subprocess.DEVNULL,
    )
args = [
    "docker",
    "--host",
    "unix:///var/run/docker.sock",
    "create",
    "-i",
    "--name",
    name,
    "--label",
    "io.nexus.kind=public-api",
    "--label",
    f"io.nexus.owner={owner}",
    "--user",
    "10001:10001",
    "--read-only",
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges:true",
    "--pids-limit",
    "128",
    "--memory",
    "512m",
    "--memory-swap",
    "512m",
    "--cpus",
    "1",
    "--tmpfs",
    "/tmp:rw,noexec,nosuid,nodev,size=128m,uid=10001,gid=10001,mode=700",
    "--mount",
    f"type=bind,src={state / 'control'},dst=/run/nexus-control,readonly",
    "--network",
    network,
    "--publish",
    f"127.0.0.1:{host.port}:8000",
    "--log-driver",
    "none",
    image,
]
if settings.assurance_catalog_dir:
    archive = Path(settings.assurance_catalog_dir)
    if not archive.is_absolute() or not archive.is_dir() or archive.is_symlink():
        raise SystemExit("EXPLICIT_REGULAR_ASSURANCE_DIRECTORY_REQUIRED")
    config["assurance_catalog_dir"] = "/run/nexus-assurance"
    args[-1:-1] = [
        "--mount",
        f"type=bind,src={archive},dst=/run/nexus-assurance,readonly",
    ]
cid = subprocess.check_output(args, text=True).strip()
process = subprocess.Popen(
    ["docker", "--host", "unix:///var/run/docker.sock", "start", "-ai", cid],
    stdin=subprocess.PIPE,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
process.stdin.write(json.dumps(config).encode() + b"\n")
process.stdin.flush()


def stop(*_):
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, stop)
try:
    print(
        f"Confined public API starting on 127.0.0.1:{host.port}; no Docker socket/CLI mounted",
        flush=True,
    )
    while process.poll() is None:
        time.sleep(0.5)
    if process.returncode:
        raise SystemExit("Confined API process failed")
except KeyboardInterrupt:
    pass
finally:
    try:
        subprocess.run(
            [
                "docker",
                "--host",
                "unix:///var/run/docker.sock",
                "stop",
                "--time",
                "30",
                cid,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=40,
        )
    except (OSError, subprocess.TimeoutExpired):
        print(
            "Confined API graceful stop incomplete; attempting owned removal",
            flush=True,
        )
    subprocess.run(
        ["docker", "--host", "unix:///var/run/docker.sock", "rm", "-f", cid],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if process.stdin:
        process.stdin.close()
    process.wait(timeout=5)
