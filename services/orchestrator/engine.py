"""Fixed Docker CLI backend. Only this trusted infrastructure module accesses the daemon."""

import json
import os
import re
import subprocess
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
STATE = Path(os.environ.get("NEXUS_RUNTIME_STATE_DIR", ROOT / ".runtime")).resolve()
# Trusted host configuration only. Model inputs are validated and mounted read-only;
# execution claims/control material always remain under the selected STATE.
MODEL_STATE = Path(os.environ.get("NEXUS_MODEL_STATE_DIR", STATE)).resolve()
CONFIG_FILE = Path(os.environ.get("NEXUS_CONFIG_FILE", ROOT / "apps/api/.env"))
LABEL = "io.nexus.owner"
ROLES = {"red", "blue", "model", "gateway"}


class EngineError(Exception):
    pass


def image_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise ValueError("Immutable allowlisted image identity required")
    return value


class DockerEngine:
    def __init__(self, guard=lambda: None):
        self.guard = guard

    def command(self, *args, input=None, timeout=15):
        self.guard()
        try:
            result = subprocess.run(
                ["docker", "--host", "unix:///var/run/docker.sock", *args],
                input=input,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise EngineError("DOCKER_OPERATION_UNAVAILABLE") from None
        if result.returncode:
            raise EngineError("DOCKER_OPERATION_FAILED")
        return result.stdout

    def json(self, *args):
        return json.loads(self.command(*args))

    def profile(self):
        info = self.json("info", "--format", "{{json .}}")
        required = info.get("CgroupVersion") == "2" and all(
            info.get(k) for k in ("MemoryLimit", "PidsLimit")
        )
        seccomp = any("seccomp" in s for s in info.get("SecurityOptions", []))
        return {
            "available": required
            and seccomp
            and int(info["ServerVersion"].split(".")[0]) >= 28,
            "profile": "rootless"
            if any("rootless" in s for s in info.get("SecurityOptions", []))
            else "rootful",
            "engine_version": info["ServerVersion"],
            "cgroups": "v2" if info.get("CgroupVersion") == "2" else "unsupported",
            "seccomp": seccomp,
            "block_io": "UNSUPPORTED",
        }

    def resources(self, kind, owner, evaluation=None):
        UUID(owner)
        args = (
            ["container", "ls", "-aq"]
            if kind == "container"
            else ["network", "ls", "-q"]
        )
        args += ["--filter", f"label={LABEL}={owner}"]
        if evaluation:
            UUID(str(evaluation))
            args += ["--filter", f"label=io.nexus.evaluation={evaluation}"]
        return self.command(*args).decode().split()

    def cleanup(self, owner, evaluation):
        # Labels bind ownership; never wildcard-remove Docker resources.
        failed = False
        for cid in self.resources("container", owner, evaluation):
            inspect = self.json("inspect", cid)[0]
            if inspect["Config"]["Labels"].get(LABEL) != owner or inspect["Config"][
                "Labels"
            ].get("io.nexus.evaluation") != str(evaluation):
                continue
            if inspect["Config"]["Labels"].get("io.nexus.kind") not in {
                "red",
                "blue",
                "model",
                "gateway",
                "witness",
            }:
                continue
            try:
                self.command("rm", "-f", cid)
            except EngineError:
                failed = True
        for nid in self.resources("network", owner, evaluation):
            inspect = self.json("network", "inspect", nid)[0]
            if inspect["Labels"].get(LABEL) != owner or inspect["Labels"].get(
                "io.nexus.evaluation"
            ) != str(evaluation):
                continue
            if inspect["Labels"].get("io.nexus.kind") not in {
                "network",
                "witness_network",
            }:
                continue
            try:
                self.command("network", "rm", nid)
            except EngineError:
                failed = True
        return (
            not failed
            and not self.resources("container", owner, evaluation)
            and not self.resources("network", owner, evaluation)
        )

    def credentials_revoked(self, owner, evaluation):
        # Ephemeral HMAC keys exist only in these processes. A failed observation
        # is not proof of revocation; stopped processes cannot serve the old keys.
        for cid in self.resources("container", owner, evaluation):
            item = self.json("inspect", cid)[0]
            if (
                item["Config"]["Labels"].get("io.nexus.kind") in ROLES
                and item["State"]["Running"]
            ):
                return False
        return True


def template(
    role,
    image,
    owner,
    evaluation,
    network,
    run_id,
    *,
    model_profile=False,
    assigned_cpus=None,
):
    if role not in ROLES:
        raise ValueError("Workload role not allowed")
    if type(model_profile) is not bool or (model_profile and role != "model"):
        raise ValueError("The fixed real-model profile is restricted to the model role")
    UUID(owner)
    UUID(str(evaluation))
    UUID(run_id)
    if not re.fullmatch(r"[a-f0-9]{64}", network):
        raise ValueError("Only an owned Docker network ID is accepted")
    from services.orchestrator.cpu_topology import cpu_list, format_cpus

    if assigned_cpus is not None and not cpu_list(format_cpus(assigned_cpus)):
        raise ValueError("EMPTY_ASSIGNED_CPUSET")
    return [
        "create",
        "--pull",
        "never",
        "-i",
        "--name",
        f"nexus-{str(evaluation)[:8]}-{role}-{run_id[:8]}",
        "--label",
        f"{LABEL}={owner}",
        "--label",
        f"io.nexus.evaluation={evaluation}",
        "--label",
        f"io.nexus.kind={role}",
        "--label",
        f"io.nexus.run={run_id}",
        "--user",
        "10001:10001",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "64" if model_profile else "32",
        "--memory",
        "1g" if model_profile else "128m",
        "--memory-swap",
        "1g" if model_profile else "128m",
        "--cpus",
        "2" if model_profile else "0.5",
        *(
            ["--cpuset-cpus", format_cpus(assigned_cpus)]
            if assigned_cpus is not None
            else []
        ),
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=32m,uid=10001,gid=10001,mode=700",
        "--network",
        network,
        "--restart",
        "no",
        "--log-driver",
        "none",
        *(
            [
                "--mount",
                f"type=bind,src={MODEL_STATE / 'model-cache/qwen-0.5b'},dst=/opt/model,readonly",
            ]
            if model_profile
            else []
        ),
        *(["--sysctl", "net.ipv4.ip_forward=0"] if role == "gateway" else []),
        image_id(image),
    ]


def start(engine, cid, config):
    process = subprocess.Popen(
        ["docker", "--host", "unix:///var/run/docker.sock", "start", "-ai", cid],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if config is not None:
        process.stdin.write(json.dumps(config, separators=(",", ":")).encode() + b"\n")
        process.stdin.flush()
    return process


def effective(inspect, health, *, model_profile=False):
    host, config = inspect["HostConfig"], inspect["Config"]
    security = set(health["security"])
    flags = {
        "non_root": config["User"] == "10001:10001" and health["uid"] == 10001,
        "read_only": host["ReadonlyRootfs"],
        "no_capabilities": "ALL" in host["CapDrop"]
        and "CapEff:\t0000000000000000" in security,
        "no_new_privileges": any("no-new-privileges" in x for x in host["SecurityOpt"])
        and "NoNewPrivs:\t1" in security,
        "seccomp": "Seccomp:\t2" in security
        and not any("unconfined" in x for x in host["SecurityOpt"]),
        "private_namespaces": host["NetworkMode"] not in {"host", "none"}
        and host.get("PidMode", "") not in {"host"},
        "approved_read_only_model_mount"
        if model_profile
        else "no_host_mounts": not host.get("Binds")
        and not host.get("Privileged")
        and not host.get("PortBindings")
        and (
            not host.get("Mounts")
            if not model_profile
            else len(host.get("Mounts", [])) == 1
            and any(
                m["Type"] == "bind"
                and m["Source"] == str(MODEL_STATE / "model-cache/qwen-0.5b")
                and m["Destination"] == "/opt/model"
                and m["RW"] is False
                for m in inspect["Mounts"]
            )
        ),
        "limits": host["Memory"] == (1073741824 if model_profile else 134217728)
        and host["MemorySwap"] == (1073741824 if model_profile else 134217728)
        and host["PidsLimit"] == (64 if model_profile else 32)
        and host["NanoCpus"] == (2000000000 if model_profile else 500000000),
        "cgroups": health["cgroups"]["memory.max"]
        == ("1073741824" if model_profile else "134217728")
        and health["cgroups"]["pids.max"] == ("64" if model_profile else "32")
        and health["cgroups"]["cpu.max"]
        == ("200000 100000" if model_profile else "50000 100000"),
        "no_default_route": not health["default_route"],
        "tmpfs": "/tmp" in host.get("Tmpfs", {})
        and all(x in host["Tmpfs"]["/tmp"] for x in ("noexec", "nosuid", "nodev")),
    }
    if not all(flags.values()):
        raise EngineError("EFFECTIVE_HARDENING_FAILED")
    return flags
