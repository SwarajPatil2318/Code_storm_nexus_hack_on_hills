"""Private stdin bootstrap inside the confined signer, never a public endpoint."""

import json
import os
import pathlib
import shutil
import sys

sys.path[:0] = ["/opt/nexus", "/opt/vendor"]


def main():
    if (
        os.getuid() == 0
        or pathlib.Path("/var/run/docker.sock").exists()
        or shutil.which("docker")
    ):
        raise ValueError("SIGNER_CONFINEMENT_REQUIRED")
    raw = sys.stdin.buffer.readline(65537)
    if len(raw) > 65536:
        raise ValueError("SIGNER_CONFIGURATION_BOUND")
    config = json.loads(raw)
    from nexus_api.proof_identity import KEY_PATH, SIGNER_GID, SIGNER_UID

    if (
        os.getuid() != SIGNER_UID
        or os.getgid() != SIGNER_GID
        or "private_key_pem" in config
    ):
        raise ValueError("DEDICATED_SIGNER_IDENTITY_REQUIRED")
    config["private_key"] = KEY_PATH
    from services.signing.worker import run

    run(config)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - never log configuration or key input
        print(
            json.dumps(
                {"event": "signer_exit", "exception_type": type(error).__name__}
            ),
            flush=True,
        )
        raise SystemExit(1) from None
