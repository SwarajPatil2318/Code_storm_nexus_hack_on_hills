"""Operator-controlled volume custody. Keys never enter the host launcher process."""

import argparse
import base64
import getpass
import json
import os
import subprocess
from pathlib import Path

from nexus_api.proof_identity import SIGNER_GID, SIGNER_UID

from services.orchestrator.engine import image_id
from services.orchestrator.host_profile import name

ROOT = Path(__file__).resolve().parents[1]
D = ["docker", "--host", "unix:///var/run/docker.sock"]


def volume_info(volume, owner):
    value = json.loads(
        subprocess.check_output(
            [*D, "volume", "inspect", volume], text=True, timeout=15
        )
    )[0]
    labels = value.get("Labels") or {}
    if (
        value["Driver"] != "local"
        or value.get("Options")
        or value["Scope"] != "local"
        or labels.get("io.nexus.kind") != "proof-key"
        or labels.get("io.nexus.owner") != owner
        or labels.get("io.nexus.identity") != f"{SIGNER_UID}:{SIGNER_GID}"
    ):
        raise ValueError("VERIFIED_PRIVATE_KEY_VOLUME_REQUIRED")
    return value


def operation(volume, image, config, *, writable=False, prepare=False):
    args = [
        *D,
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "32",
        "--memory",
        "128m",
        "--cpus",
        "0.5",
        "--log-driver",
        "none",
        "--user",
        "0:0" if prepare else f"{SIGNER_UID}:{SIGNER_GID}",
    ]
    if prepare:
        args += ["--cap-add", "CHOWN"]
    args += [
        "--mount",
        f"type=volume,src={volume},dst=/run/nexus-proof-key"
        + ("" if writable else ",readonly"),
        "--entrypoint",
        "python",
        image,
        "-I",
        "/opt/nexus/custody_entrypoint.py",
    ]
    response = subprocess.run(
        args,
        input=json.dumps(config).encode() + b"\n",
        capture_output=True,
        check=False,
        timeout=30,
    )
    if response.returncode:
        raise ValueError("CUSTODY_OPERATION_REJECTED")
    return json.loads(response.stdout)


def create(volume, image, owner, *, test=False):
    # Existing volumes are never reused, overwritten or automatically removed.
    exists = subprocess.run(
        [*D, "volume", "inspect", volume], capture_output=True, check=False, timeout=15
    )
    if exists.returncode == 0:
        raise ValueError("EXISTING_KEY_VOLUME_PRESERVED")
    subprocess.run(
        [
            *D,
            "volume",
            "create",
            "--label",
            "io.nexus.kind=proof-key",
            "--label",
            "io.nexus.owner=" + owner,
            "--label",
            f"io.nexus.identity={SIGNER_UID}:{SIGNER_GID}",
            "--label",
            "io.nexus.disposable-test=" + str(test).lower(),
            volume,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        timeout=15,
    )
    volume_info(volume, owner)
    operation(volume, image, {"action": "prepare"}, writable=True, prepare=True)


def write_new(path, value):
    path = Path(path)
    if (
        path.resolve().is_relative_to(ROOT)
        or path.resolve().is_relative_to(ROOT.parent / "Hack_on_Hills-release")
        or any(p.is_symlink() for p in path.parents)
    ):
        raise ValueError("EXTERNAL_BACKUP_OR_PUBLIC_OUTPUT_REQUIRED")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(value, file, indent=2)
        file.flush()
        os.fsync(file.fileno())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action", choices=["init", "backup", "restore", "selftest", "destroy-test"]
    )
    p.add_argument("--volume", type=name, required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--disposable-test", action="store_true")
    p.add_argument("--expected-key-id")
    p.add_argument("--output", type=Path)
    p.add_argument("--backup", type=Path)
    p.add_argument("--passphrase-fd", type=int)
    a = p.parse_args()
    if not a.apply:
        print("Plan only: named-volume key custody; no key, account or service changes")
        return
    from services.orchestrator.engine import STATE

    image = image_id((STATE / "signer-image").read_text().strip())
    owner = (STATE / "owner").read_text().strip()
    if a.action in {"init", "restore"}:
        create(a.volume, image, owner, test=a.disposable_test)
    meta = volume_info(a.volume, owner)
    if a.action == "destroy-test":
        if (meta.get("Labels") or {}).get("io.nexus.disposable-test") != "true":
            raise ValueError("PERMANENT_KEY_DELETION_FORBIDDEN")
        subprocess.run(
            [*D, "volume", "rm", a.volume],
            check=True,
            stdout=subprocess.DEVNULL,
            timeout=15,
        )
        print("Owned disposable test key volume removed")
        return
    config = {
        "action": "generate" if a.action == "init" else a.action,
        "expected_key_id": a.expected_key_id,
    }
    if a.action in {"backup", "restore"}:
        raw = (
            os.read(a.passphrase_fd, 1024)
            if a.passphrase_fd is not None
            else getpass.getpass("Recovery passphrase (never stored): ").encode()
        )
        config["passphrase"] = base64.b64encode(raw).decode()
    if a.action == "restore":
        if a.backup.is_symlink() or a.backup.stat().st_size > 65536:
            raise ValueError("BACKUP_LIMIT")
        config["backup"] = json.loads(a.backup.read_text())
    result = operation(
        a.volume, image, config, writable=a.action in {"init", "restore"}
    )
    if a.output:
        write_new(a.output, result)
    elif a.action == "backup":
        raise ValueError("EXTERNAL_BACKUP_OUTPUT_REQUIRED")
    else:
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - no private exception values
        raise SystemExit("CUSTODY_FAILED:" + type(error).__name__) from None
