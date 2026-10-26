"""Trusted explicit image build: fixed Dockerfiles, no operator-controlled build inputs."""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from services.orchestrator.engine import STATE
from services.orchestrator.host_profile import name as host_name

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--tag-prefix", type=host_name, default="nexus")
args = parser.parse_args()
state = STATE
state.mkdir(mode=0o700, exist_ok=True)
images = {}
context_holder = tempfile.TemporaryDirectory(prefix="nexus-fixed-runtime-")
context = Path(context_holder.name)
for name in (
    "Dockerfile",
    "wire.py",
    "worker.py",
    "gateway.py",
    "bootstrap.py",
    "providers.py",
):
    shutil.copy(ROOT / "services/runtime" / name, context / name)
shutil.copy(
    ROOT / "apps/api/nexus_api/evaluation_rules.py", context / "evaluation_rules.py"
)
for role in ("red", "blue", "model", "gateway"):
    tag = {
        "red": "nexus-red-runner",
        "blue": "nexus-blue-defence",
        "model": "nexus-model-worker",
        "gateway": "nexus-broker-gateway",
    }[role].replace("nexus-", args.tag_prefix + "-", 1) + ":m4"
    subprocess.run(
        [
            "docker",
            "--host",
            "unix:///var/run/docker.sock",
            "build",
            "--build-arg",
            f"WORKLOAD_ROLE={role}",
            "-t",
            tag,
            str(context),
        ],
        check=True,
    )
    images[role] = subprocess.check_output(
        [
            "docker",
            "--host",
            "unix:///var/run/docker.sock",
            "image",
            "inspect",
            tag,
            "--format",
            "{{.Id}}",
        ],
        text=True,
    ).strip()
path = state / "images.json"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as out:
    json.dump(images, out, indent=2)
print("Built four immutable fixed runtime images; private allowlist recorded")

context_holder.cleanup()
