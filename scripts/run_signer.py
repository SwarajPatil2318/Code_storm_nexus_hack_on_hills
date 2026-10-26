"""Trusted launcher: dedicated signer, read-only key volume, public/config stdin."""

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from nexus_api.proof_identity import SIGNER_GID, SIGNER_UID, prepare_claim_readers
from sqlalchemy.engine import make_url

from scripts.proof_custody import volume_info
from services.orchestrator.engine import STATE, image_id
from services.orchestrator.host_profile import name

ROOT = Path(__file__).resolve().parents[1]
D = ["docker", "--host", "unix:///var/run/docker.sock"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--name", type=name, default="nexus-proof-signer")
    p.add_argument("--compose-project", type=name, default="nexus")
    a = p.parse_args()
    if (
        a.config.is_symlink()
        or a.config.stat().st_mode & 0o077
        or a.config.stat().st_size > 32768
    ):
        raise SystemExit("PRIVATE_SIGNER_CONFIG_REQUIRED")
    config = json.loads(a.config.read_text())
    if "private_key" in config or "private_key_pem" in config:
        raise SystemExit("LEGACY_HOST_KEY_CONFIG_REJECTED")
    volume = name(config.pop("key_volume"))
    owner = (STATE / "owner").read_text().strip()
    locks = STATE / "job-locks"
    locks.mkdir(mode=0o700, exist_ok=True)
    prepare_claim_readers(locks, owner)
    volume_info(volume, owner)
    if os.getuid() == 0:
        raise SystemExit("NONROOT_HOST_IDENTITY_REQUIRED")
    image = image_id((STATE / "signer-image").read_text().strip())
    ids = subprocess.check_output(
        [
            *D,
            "ps",
            "-q",
            "--filter",
            "label=com.docker.compose.project=" + a.compose_project,
            "--filter",
            "label=com.docker.compose.service=postgres",
        ],
        text=True,
        timeout=15,
    ).split()
    if len(ids) != 1:
        raise SystemExit("ONE_SELECTED_DATABASE_REQUIRED")
    pg = json.loads(
        subprocess.check_output([*D, "inspect", ids[0]], text=True, timeout=15)
    )[0]
    network = next(iter(pg["NetworkSettings"]["Networks"]))
    existing = subprocess.run(
        [*D, "inspect", a.name], capture_output=True, check=False, timeout=15
    )
    if existing.returncode == 0:
        raise SystemExit("SIGNER_NAME_IN_USE; existing service preserved")
    config["database_url"] = (
        make_url(config["database_url"])
        .set(host="postgres", port=5432)
        .render_as_string(hide_password=False)
    )
    config.update(
        runtime_uid=os.getuid(), runtime_owner=owner, lock_dir="/run/nexus-job-locks"
    )
    cid = subprocess.check_output(
        [
            *D,
            "create",
            "-i",
            "--name",
            a.name,
            "--label",
            "io.nexus.kind=proof-signer",
            "--label",
            "io.nexus.owner=" + owner,
            "--user",
            f"{SIGNER_UID}:{SIGNER_GID}",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "64",
            "--memory",
            "256m",
            "--memory-swap",
            "256m",
            "--cpus",
            "0.5",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size=16m,uid={SIGNER_UID},gid={SIGNER_GID},mode=700",
            "--mount",
            f"type=bind,src={locks},dst=/run/nexus-job-locks,readonly",
            "--mount",
            f"type=volume,src={volume},dst=/run/nexus-proof-key,readonly",
            "--network",
            network,
            "--restart",
            "no",
            "--log-driver",
            "none",
            image,
        ],
        text=True,
        timeout=15,
    ).strip()
    proc = subprocess.Popen(
        [*D, "start", "-ai", cid],
        stdin=subprocess.PIPE,
        stdout=None,
        stderr=subprocess.DEVNULL,
    )
    proc.stdin.write(json.dumps(config).encode() + b"\n")
    proc.stdin.flush()

    def stop(*_):
        raise KeyboardInterrupt

    for sig in [signal.SIGTERM, signal.SIGINT]:
        signal.signal(sig, stop)
    try:
        print(
            "Dedicated evidence signer starting; no public listener or Docker access; read-only private key volume",
            flush=True,
        )
        while proc.poll() is None:
            time.sleep(0.2)
        if proc.returncode:
            raise SystemExit("CONFINED_SIGNER_EXITED")
    except KeyboardInterrupt:
        pass
    finally:
        subprocess.run(
            [*D, "stop", "--time", "30", cid],
            capture_output=True,
            timeout=40,
            check=False,
        )
        subprocess.run([*D, "rm", cid], capture_output=True, timeout=15, check=False)


if __name__ == "__main__":
    main()
