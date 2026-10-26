"""Build a fixed CPU model worker from verified local artifacts, never tenant build inputs."""

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from services.orchestrator.engine import MODEL_STATE, STATE

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--tag", default="nexus-local-model:m5")
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="nexus-model-build-") as directory:
    context = Path(directory)
    for name in ("wire.py", "worker.py", "gateway.py", "bootstrap.py", "providers.py"):
        shutil.copy(ROOT / "services/runtime" / name, context / name)
    shutil.copy(
        ROOT / "apps/api/nexus_api/evaluation_rules.py", context / "evaluation_rules.py"
    )
    shutil.copytree(MODEL_STATE / "inference-bin", context / "inference-bin")
    shutil.copy(ROOT / "services/runtime/Dockerfile.model", context / "Dockerfile")
    subprocess.run(
        [
            "docker",
            "--host",
            "unix:///var/run/docker.sock",
            "build",
            "-t",
            args.tag,
            str(context),
        ],
        check=True,
    )
image = subprocess.check_output(
    [
        "docker",
        "--host",
        "unix:///var/run/docker.sock",
        "image",
        "inspect",
        args.tag,
        "--format",
        "{{.Id}}",
    ],
    text=True,
).strip()
manifest = json.loads((MODEL_STATE / "model-cache/qwen-0.5b/manifest.json").read_text())
manifest["image"] = image
(STATE / "model-runtime.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(
    "Built immutable isolated CPU model image; trusted model runtime allowlist recorded"
)
