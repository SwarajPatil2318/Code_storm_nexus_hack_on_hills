"""Build the confined API from explicit hash-checked wheels, never ambient packages."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from services.orchestrator.engine import STATE

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--tag", default="nexus-public-api:m4")
    args = parser.parse_args()
    source = (
        ["--no-index", "--find-links", str(args.wheelhouse.resolve())]
        if args.wheelhouse
        else ["--index-url", "https://pypi.org/simple"]
    )
    with tempfile.TemporaryDirectory(prefix="nexus-api-build-") as directory:
        context = Path(directory)
        # Use a clean target, binary wheels only and the committed runtime closure.
        # pip validates wheel hashes and fails if a transitive dependency is absent.
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "--isolated",
                "install",
                *source,
                "--require-hashes",
                "--only-binary=:all:",
                "--no-compile",
                "--target",
                str(context / "vendor"),
                "-r",
                str(ROOT / "apps/api/requirements.runtime.lock"),
            ],
            check=True,
            timeout=600,
            env={**os.environ, "PYTHONNOUSERSITE": "1"},
        )
        shutil.copytree(
            ROOT / "apps/api/nexus_api",
            context / "nexus_api",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copy(
            ROOT / "services/runtime/api_entrypoint.py", context / "api_entrypoint.py"
        )
        shutil.copy(ROOT / "services/runtime/Dockerfile.api", context / "Dockerfile")
        # Operators use umask 077 for secrets. Application code/wheels must still
        # be readable by the image's fixed UID 10001; no private config is copied.
        for path in context.rglob("*"):
            if path.is_symlink():
                raise ValueError("Unexpected symlink in API build inputs")
            path.chmod(0o755 if path.is_dir() else 0o644)
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
            timeout=600,
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
        timeout=15,
    ).strip()
    state = STATE
    state.mkdir(mode=0o700, exist_ok=True)
    target = state / "api-image"
    # Replace only after a successful build; preserve old allowlist on failure.
    temporary = state / "api-image.pending"
    temporary.write_text(image + "\n")
    temporary.chmod(0o600)
    temporary.replace(target)
    print("Confined API image built from hash-checked runtime wheels")


if __name__ == "__main__":
    main()
