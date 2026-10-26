"""Build code-only signer from the approved immutable confined API dependency base."""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from services.orchestrator.engine import STATE, image_id

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tag", default="nexus-proof-signer:m8")
    a = p.parse_args()
    base = image_id((STATE / "api-image").read_text().strip())
    with tempfile.TemporaryDirectory(prefix="nexus-signer-build-") as directory:
        directory = Path(directory)
        for name in [
            "worker.py",
            "entrypoint.py",
            "custody.py",
            "custody_entrypoint.py",
            "Dockerfile",
        ]:
            shutil.copy2(ROOT / "services/signing" / name, directory / name)
            (directory / name).chmod(0o644)
        subprocess.run(
            [
                "docker",
                "--host",
                "unix:///var/run/docker.sock",
                "build",
                "--build-arg",
                "NEXUS_API_BASE=" + base,
                "--tag",
                a.tag,
                str(directory),
            ],
            check=True,
            timeout=120,
        )
    value = subprocess.check_output(
        [
            "docker",
            "--host",
            "unix:///var/run/docker.sock",
            "image",
            "inspect",
            a.tag,
            "--format",
            "{{.Id}}",
        ],
        text=True,
        timeout=15,
    ).strip()
    image_id(value)
    target = STATE / "signer-image"
    temporary = target.with_suffix(".pending")
    temporary.write_text(value + "\n")
    temporary.chmod(0o600)
    temporary.replace(target)
    print(
        "Code-only confined signer image built; no key/configuration in build context"
    )


if __name__ == "__main__":
    main()
