"""Read-only Linux topology. CPU numbers and placement never come from tenants."""

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


class TopologyError(ValueError):
    pass


def cpu_list(value):
    result = set()
    for part in value.strip().split(","):
        if not part:
            continue
        bounds = part.split("-")
        if len(bounds) > 2 or any(not v.isdecimal() for v in bounds):
            raise TopologyError("INVALID_CPU_LIST")
        lo, hi = int(bounds[0]), int(bounds[-1])
        if not 0 <= lo <= hi < 4096:
            raise TopologyError("INVALID_CPU_RANGE")
        result.update(range(lo, hi + 1))
    return frozenset(result)


def format_cpus(values):
    return ",".join(map(str, sorted(values)))


@dataclass(frozen=True)
class Core:
    package: int
    core: int
    cpus: tuple[int, ...]
    nodes: tuple[int, ...]
    core_type: int | None
    capacity: int | None
    max_khz: int | None

    @property
    def key(self):
        return f"{self.package}:{self.core}"

    @property
    def cpu_class(self):
        # Frequency/capacity are matching strata, not proof of equal performance.
        return (
            self.core_type,
            self.capacity,
            self.max_khz,
            len(self.cpus),
            self.package,
            self.nodes,
        )


@dataclass(frozen=True)
class Topology:
    allowed: tuple[int, ...]
    memory_nodes: tuple[int, ...]
    cores: tuple[Core, ...]
    cgroup_path: str

    @property
    def digest(self):
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode()
        ).hexdigest()

    def pool(self):
        classes = {}
        for core in self.cores:
            classes.setdefault(core.cpu_class, []).append(core)
        # Keep one entire physical core in the chosen class outside the pool,
        # plus all other classes. At most two active allocations, one core each.
        eligible = [v for v in classes.values() if len(v) >= 3]
        if not eligible:
            raise TopologyError("INSUFFICIENT_MATCHED_CORES_WITH_HOST_RESERVE")
        selected = max(
            eligible,
            key=lambda v: (v[0].capacity or 0, v[0].max_khz or 0, len(v[0].cpus)),
        )
        return tuple(sorted(selected, key=lambda c: (c.package, c.core))[:2])


def discover(
    sysfs=Path("/sys/devices/system"),
    cgroup=Path("/sys/fs/cgroup"),
    *,
    affinity=None,
    membership=None,
):
    try:
        online = cpu_list((sysfs / "cpu/online").read_text())
        allowed = (
            set(os.sched_getaffinity(0) if affinity is None else affinity) & online
        )
        if membership is None:
            membership = Path("/proc/self/cgroup").read_text()
        lines = membership.strip().splitlines()
        if len(lines) != 1 or not lines[0].startswith("0::"):
            raise TopologyError("CGROUP_V2_REQUIRED")
        relative = lines[0][3:].lstrip("/")
        if ".." in Path(relative).parts:
            raise TopologyError("INVALID_CGROUP_PATH")
        current = cgroup / relative
        if not current.is_dir():
            raise TopologyError("CGROUP_HIERARCHY_UNVERIFIED")
        nodes = cpu_list((sysfs / "node/online").read_text())
        while True:
            cpu_file, mem_file = (
                current / "cpuset.cpus.effective",
                current / "cpuset.mems.effective",
            )
            if cpu_file.exists() != mem_file.exists():
                raise TopologyError("INCOMPLETE_CPUSET_HIERARCHY")
            if cpu_file.exists():
                allowed &= cpu_list(cpu_file.read_text())
                nodes &= cpu_list(mem_file.read_text())
            elif current == cgroup:
                raise TopologyError("ROOT_CPUSET_UNAVAILABLE")
            if current == cgroup:
                break
            current = current.parent
        if not allowed or not nodes or not (cgroup / "cgroup.controllers").exists():
            raise TopologyError("EFFECTIVE_CPUSET_UNAVAILABLE")
        records = {}
        for cpu in sorted(online):
            base = sysfs / f"cpu/cpu{cpu}"
            topology = base / "topology"
            siblings = cpu_list((topology / "thread_siblings_list").read_text())
            package = int((topology / "physical_package_id").read_text())
            core = int((topology / "core_id").read_text())
            if cpu not in siblings or package < 0 or core < 0:
                raise TopologyError("INVALID_PHYSICAL_TOPOLOGY")

            record = (package, core, siblings)
            records[cpu] = record
            if not siblings <= allowed:
                continue  # Never allocate only part of an SMT core.
            for sibling in siblings:
                other = sysfs / f"cpu/cpu{sibling}/topology"
                if (
                    cpu_list((other / "thread_siblings_list").read_text()) != siblings
                    or int((other / "physical_package_id").read_text()) != package
                    or int((other / "core_id").read_text()) != core
                ):
                    raise TopologyError("INCONSISTENT_SMT_TOPOLOGY")
        cores = {}
        for cpu, (package, core, siblings) in records.items():
            if not siblings <= allowed:
                continue
            base = sysfs / f"cpu/cpu{cpu}"

            def read_optional(name, base=base):
                p = base / name
                return int(p.read_text()) if p.exists() else None

            node_ids = tuple(sorted(int(p.name[4:]) for p in base.glob("node[0-9]*")))
            if not node_ids or not set(node_ids) <= nodes:
                raise TopologyError("NUMA_PLACEMENT_UNVERIFIED")
            item = Core(
                package,
                core,
                tuple(sorted(siblings)),
                node_ids,
                read_optional("topology/core_type"),
                read_optional("cpu_capacity"),
                read_optional("cpufreq/cpuinfo_max_freq"),
            )
            key = (package, core)
            if key in cores and cores[key] != item:
                raise TopologyError("INCONSISTENT_CPU_CLASS")
            cores[key] = item
        if "cpuset" not in (cgroup / "cgroup.controllers").read_text().split():
            raise TopologyError("CPUSET_CONTROLLER_UNAVAILABLE")
        if any(
            c.core_type is None and c.capacity is None and c.max_khz is None
            for c in cores.values()
        ):
            raise TopologyError("CPU_CLASS_UNVERIFIED")
        result = Topology(
            tuple(sorted(allowed)),
            tuple(sorted(nodes)),
            tuple(cores.values()),
            relative,
        )
        result.pool()
        return result
    except (OSError, ValueError, StopIteration) as error:
        if isinstance(error, TopologyError):
            raise
        raise TopologyError("TOPOLOGY_UNAVAILABLE") from None
