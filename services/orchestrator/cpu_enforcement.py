"""Private verification of owned cgroups and all visible workload thread affinities."""

import json

from services.orchestrator.cpu_topology import cpu_list, format_cpus
from services.orchestrator.engine import EngineError

CAPTURE = """import os,pathlib,json
p=pathlib.Path('/sys/fs/cgroup');a={};gone=0
for task in pathlib.Path('/proc').glob('[0-9]*/task/[0-9]*'):
 try:a[str(task)]=sorted(os.sched_getaffinity(int(task.name)))
 except ProcessLookupError:gone+=1
print(json.dumps({'cpus':p.joinpath('cpuset.cpus.effective').read_text().strip(),'threads':a,'departed_threads':gone}))
"""


def verify(engine, cid, owner, eid, assigned):
    item = engine.json("inspect", cid)[0]
    labels = item["Config"]["Labels"] or {}
    if (
        labels.get("io.nexus.owner") != owner
        or labels.get("io.nexus.evaluation") != str(eid)
        or labels.get("io.nexus.kind") not in {"red", "blue", "model", "gateway"}
    ):
        raise EngineError("CPU_AFFINITY_OWNERSHIP_FAILED")
    expected = set(assigned)
    if not expected or cpu_list(item["HostConfig"]["CpusetCpus"]) != expected:
        raise EngineError("CPU_AFFINITY_CONFIGURATION_FAILED")
    observed = json.loads(engine.command("exec", cid, "python", "-I", "-c", CAPTURE))
    if (
        cpu_list(observed["cpus"]) != expected
        or not observed["threads"]
        or any(not v or not set(v) <= expected for v in observed["threads"].values())
    ):
        raise EngineError("EFFECTIVE_CPU_AFFINITY_FAILED")
    return {
        "cpuset": format_cpus(expected),
        "thread_count": len(observed["threads"]),
        "verified": True,
    }
