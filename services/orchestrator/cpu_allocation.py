"""One host-private, crash-durable CPU journal shared by participating provisioners.

A reservation never expires into reuse. Only verified owned teardown can release it.
The journal is outside per-installation STATE; this is not host-exclusive isolation.
"""

import fcntl
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from services.orchestrator.cpu_topology import cpu_list, discover
from services.orchestrator.engine import ROOT

JOURNAL = ROOT / ".runtime/cpu-allocations"


class CapacityError(ValueError):
    pass


class AllocationManager:
    def __init__(self, engine, directory=None, topology=None):
        self.engine, self.directory, self.topology = (
            engine,
            Path(directory or os.environ.get("NEXUS_CPU_ALLOCATION_DIR", JOURNAL)),
            topology or (lambda: discover(affinity=os.sched_getaffinity(os.getpid()))),
        )

    @contextmanager
    def locked(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.directory.stat().st_mode & 0o077:
            raise CapacityError("PRIVATE_ALLOCATION_DIRECTORY_REQUIRED")
        fd = os.open(
            self.directory / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.directory / "allocations.json"
            if path.is_symlink():
                raise CapacityError("ALLOCATION_SYMLINK_REFUSED")
            data = (
                json.loads(path.read_bytes())
                if path.exists()
                else {"schema": "cpu-allocations-v1", "allocations": {}}
            )
            if data.get("schema") != "cpu-allocations-v1" or not isinstance(
                data.get("allocations"), dict
            ):
                raise CapacityError("ALLOCATION_JOURNAL_INVALID")
            yield data["allocations"]
            fd, temporary = tempfile.mkstemp(dir=self.directory)
            try:
                with os.fdopen(fd, "w") as out:
                    json.dump(data, out, sort_keys=True)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temporary, path)
                directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                Path(temporary).unlink(missing_ok=True)

    def acquire(self, owner, eid, claim_id, profile):
        key = str(UUID(str(owner))) + "/" + str(UUID(str(eid)))
        claim_id = str(UUID(str(claim_id)))
        if profile not in {"STANDARD", "REDUCED_INTERFERENCE"}:
            raise CapacityError("UNKNOWN_EXECUTION_PROFILE")
        with self.locked() as allocations:
            if key in allocations:
                old = allocations[key]
                if old["claim_id"] == claim_id and old["profile"] == profile:
                    return old
                raise CapacityError("ALLOCATION_REQUIRES_RECOVERY")
            if len(allocations) >= 2 or any(
                v["profile"] != profile for v in allocations.values()
            ):
                raise CapacityError("CPU_CAPACITY_UNAVAILABLE")
            allocation = {
                "owner": str(owner),
                "evaluation_id": str(eid),
                "claim_id": claim_id,
                "profile": profile,
                "cpus": [],
                "core_keys": [],
                "topology_digest": None,
            }
            if profile == "REDUCED_INTERFERENCE":
                topology = self.topology()
                if any(
                    v["topology_digest"] != topology.digest
                    for v in allocations.values()
                ):
                    raise CapacityError("ACTIVE_TOPOLOGY_CHANGED")
                # Unknown live/created evaluation workloads are not presumed idle.
                for cid in (
                    self.engine.command(
                        "ps", "-aq", "--filter", "label=io.nexus.evaluation"
                    )
                    .decode()
                    .split()
                ):
                    item = self.engine.json("inspect", cid)[0]
                    labels = item["Config"]["Labels"] or {}
                    if labels.get("io.nexus.kind") not in {
                        "red",
                        "blue",
                        "model",
                        "gateway",
                        "witness",
                    }:
                        continue
                    other = (
                        labels.get("io.nexus.owner", "")
                        + "/"
                        + labels.get("io.nexus.evaluation", "")
                    )
                    parent = (
                        labels.get("io.nexus.owner", "")
                        + "/"
                        + labels.get("io.nexus.cpu-parent", "")
                    )
                    if other not in allocations and parent not in allocations:
                        raise CapacityError("UNMANAGED_EVALUATION_ACTIVE")
                    assigned = allocations.get(other, allocations.get(parent))
                    if cpu_list(item["HostConfig"]["CpusetCpus"]) != set(
                        assigned["cpus"]
                    ):
                        raise CapacityError("EXISTING_AFFINITY_UNVERIFIED")
                used = {c for v in allocations.values() for c in v["core_keys"]}
                core = next((c for c in topology.pool() if c.key not in used), None)
                if core is None:
                    raise CapacityError("CPU_CAPACITY_UNAVAILABLE")
                allocation.update(
                    cpus=list(core.cpus),
                    core_keys=[core.key],
                    topology_digest=topology.digest,
                )
            allocations[key] = allocation
            return allocation

    def wait(self, owner, eid, claim_id, profile, check, seconds=20):
        if not 0 <= seconds <= 30:
            raise ValueError("BOUNDED_ALLOCATION_WAIT_REQUIRED")
        deadline = time.monotonic() + seconds
        while True:
            check()
            try:
                return self.acquire(owner, eid, claim_id, profile)
            except CapacityError as error:
                if (
                    str(error)
                    not in {"CPU_CAPACITY_UNAVAILABLE", "UNMANAGED_EVALUATION_ACTIVE"}
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(0.2)

    def release(self, owner, eid, *, cleaned, revoked):
        # Independently observe absence again; caller booleans alone are insufficient.
        if not cleaned or not revoked:
            return False
        with self.locked() as allocations:
            if str(owner) + "/" + str(eid) not in allocations:
                return True
            if (
                self.engine.command(
                    "ps",
                    "-aq",
                    "--filter",
                    f"label=io.nexus.owner={owner}",
                    "--filter",
                    f"label=io.nexus.cpu-parent={eid}",
                ).strip()
                or self.engine.command(
                    "network",
                    "ls",
                    "-q",
                    "--filter",
                    f"label=io.nexus.owner={owner}",
                    "--filter",
                    f"label=io.nexus.cpu-parent={eid}",
                ).strip()
                or self.engine.resources("container", owner, eid)
                or self.engine.resources("network", owner, eid)
                or not self.engine.credentials_revoked(owner, eid)
            ):
                return False
            allocations.pop(str(owner) + "/" + str(eid), None)
            return True
