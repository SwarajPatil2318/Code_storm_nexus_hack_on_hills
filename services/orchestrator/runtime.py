"""Real restricted Docker adapters and measured predefined probes; no public Docker interface."""

import errno
import json
import secrets
import socket
import subprocess
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import uuid4

from nexus_api.runtime_schemas import Case
from nexus_api.versioning import canonical, sha

from services.orchestrator.engine import (
    DockerEngine,
    EngineError,
    effective,
    image_id,
    start,
    template,
)


class DockerRuntimeAdapter:
    isolated = True

    def __init__(
        self,
        contents,
        budget,
        *,
        owner,
        evaluation_id,
        images,
        report=lambda x: None,
        check_cancel=lambda: None,
        engine=None,
        campaign=None,
        on_model_event=lambda *_: None,
        scope_claim=lambda _: nullcontext(),
        allocation=None,
        queue_wait_ms=0,
    ):
        self.engine = engine or DockerEngine()
        self.contents, self.budget = contents, budget
        self.owner, self.evaluation_id = owner, str(evaluation_id)
        self.run_id = str(uuid4())
        self.images = {
            role: image_id(images[role]) for role in ("red", "blue", "model", "gateway")
        }
        self.report, self.check_cancel = report, check_cancel
        self.campaign = campaign
        self.real_model = (
            contents[2].get("provider") == "local"
            and contents[2].get("schema_version") == "model-manifest-v1"
        )
        self.on_model_event = on_model_event
        self.scope_claim = scope_claim
        self.last_affinity_check = 0
        self.allocation = allocation
        self.assigned_cpus = (
            allocation["cpus"]
            if allocation and allocation["profile"] == "REDUCED_INTERFERENCE"
            else None
        )
        self.processes, self.containers, self.networks = {}, {}, {}
        self.snapshot = {
            "state": "PROVISIONING",
            "profile": self.engine.profile(),
            "workloads": [],
            "probes": [],
            "cleanup": "PENDING",
            "container_count": 0,
        }
        if allocation:
            self.snapshot["isolation"] = {
                "security_profile": allocation["profile"],
                "enforcement": "PENDING" if self.assigned_cpus else "NOT_REQUIRED",
                "managed_core_nonoverlap": False,
                "host_exclusive": False,
                "allocation_digest": sha(canonical(allocation)),
                "queue_wait_ms": queue_wait_ms,
            }
        self.report(self.snapshot)

    def update(self, state=None):
        if state:
            self.snapshot["state"] = state
        self.report(self.snapshot)

    def inspect(self, cid):
        return self.engine.json("inspect", cid)[0]

    def verify_affinity(self):
        if self.snapshot.get("isolation", {}).get("enforcement") == "FAILED":
            raise EngineError("ISOLATION_ENFORCEMENT_FAILED")
        if self.assigned_cpus and time.monotonic() - self.last_affinity_check >= 1:
            from services.orchestrator.cpu_enforcement import verify

            try:
                for cid in self.containers.values():
                    verify(
                        self.engine,
                        cid,
                        self.owner,
                        self.evaluation_id,
                        self.assigned_cpus,
                    )
            except Exception:
                self.snapshot["isolation"]["enforcement"] = "FAILED"
                self.snapshot["isolation"]["managed_core_nonoverlap"] = False
                self.update()
                raise
            self.snapshot["isolation"].update(
                enforcement="VERIFIED", managed_core_nonoverlap=True
            )
            self.last_affinity_check = time.monotonic()

    def rpc(self, role, operation, payload):
        self.verify_affinity()
        data = self.engine.command(
            "exec",
            "-i",
            self.containers["gateway"],
            "python",
            "-I",
            "/opt/runtime/gateway.py",
            "control",
            input=canonical({"role": role, "operation": operation, "payload": payload})
            + b"\n",
            timeout=6,
        )
        result = json.loads(data)
        if not result.get("ok"):
            raise EngineError("AUTHENTICATED_WORKLOAD_CALL_FAILED")
        return result["result"]

    def prepare(self):
        if not self.snapshot["profile"]["available"]:
            raise EngineError("HOST_PROFILE_UNSUPPORTED")
        for role in ("red", "blue", "model"):
            self.check_cancel()
            name = f"nexus-{self.evaluation_id[:8]}-{self.run_id[:8]}-{role}"
            self.networks[role] = (
                self.engine.command(
                    "network",
                    "create",
                    "--internal",
                    "--driver",
                    "bridge",
                    "--opt",
                    "com.docker.network.bridge.gateway_mode_ipv4=isolated",
                    "--label",
                    f"io.nexus.owner={self.owner}",
                    "--label",
                    f"io.nexus.evaluation={self.evaluation_id}",
                    "--label",
                    "io.nexus.kind=network",
                    name,
                )
                .decode()
                .strip()
            )
            inspected = self.engine.json("network", "inspect", self.networks[role])[0]
            if (
                not inspected["Internal"]
                or inspected["Options"].get(
                    "com.docker.network.bridge.gateway_mode_ipv4"
                )
                != "isolated"
            ):
                raise EngineError("NETWORK_PROFILE_REJECTED")
        for role in ("red", "blue", "model", "gateway"):
            self.check_cancel()
            network = self.networks[role if role != "gateway" else "red"]
            cid = (
                self.engine.command(
                    *template(
                        role,
                        self.images[role],
                        self.owner,
                        self.evaluation_id,
                        network,
                        self.run_id,
                        model_profile=role == "model" and self.real_model,
                        assigned_cpus=self.assigned_cpus,
                    )
                )
                .decode()
                .strip()
            )
            self.containers[role] = cid
            if role != "gateway":
                self.snapshot["workloads"].append(
                    {
                        "role": role,
                        "container_id": cid[:12],
                        "image_digest": self.images[role],
                        "network_id": self.networks[role][:12],
                        "health": "CREATED",
                        "controls": {},
                        "memory_bytes": None,
                        "cpu_percent": None,
                        "memory_limit": 1073741824
                        if role == "model" and self.real_model
                        else 134217728,
                        "cpu_limit": 2 if role == "model" and self.real_model else 0.5,
                        "pids_limit": 64 if role == "model" and self.real_model else 32,
                        "resource_profile": "qwen-cpu-1g"
                        if role == "model" and self.real_model
                        else "mock-128m",
                    }
                )
                self.snapshot["container_count"] += 1
                self.update()
            if role == "gateway":
                for target in ("blue", "model"):
                    self.engine.command(
                        "network", "connect", self.networks[target], cid
                    )
            self.processes[role] = start(self.engine, cid, None)
        for role, cid in self.containers.items():
            for _ in range(40):
                inspected = self.inspect(cid)
                if inspected["State"]["Running"] and all(
                    n["IPAddress"]
                    for n in inspected["NetworkSettings"]["Networks"].values()
                ):
                    break
                time.sleep(0.05)
            else:
                raise EngineError("WORKLOAD_START_FAILED")
        gateway_networks = self.inspect(self.containers["gateway"])["NetworkSettings"][
            "Networks"
        ]

        def address(cid, nid):
            for info in self.inspect(cid)["NetworkSettings"]["Networks"].values():
                if info["NetworkID"] == nid:
                    return info["IPAddress"]
            raise EngineError("NETWORK_MEMBERSHIP_MISMATCH")

        domains, interfaces = {}, {}
        expires = int(time.time()) + (900 if self.campaign else 120)
        for index, role in enumerate(("red", "blue", "model")):
            interfaces[role] = next(
                v["IPAddress"]
                for v in gateway_networks.values()
                if v["NetworkID"] == self.networks[role]
            )
            domains[role] = {
                "key_in": secrets.token_hex(32),
                "key_out": secrets.token_hex(32),
                "ip": address(self.containers[role], self.networks[role]),
            }
            content = self.contents[index]
            config = {
                "evaluation_id": self.evaluation_id,
                "expires_at": expires,
                "key_in": domains[role]["key_in"],
                "key_out": domains[role]["key_out"],
                "artifact": content,
                "digest": sha(canonical(content)),
                "broker": interfaces[role],
            }
            if self.campaign:
                config["execution"] = {"arm": self.campaign["arm"]}
                if role == "model":
                    self.on_model_event("MODEL_LOADING", {})
            self.processes[role].stdin.write(canonical(config) + b"\n")
            self.processes[role].stdin.flush()
        config = {
            "evaluation_id": self.evaluation_id,
            "expires_at": expires,
            "domains": domains,
            "interfaces": interfaces,
        }
        self.processes["gateway"].stdin.write(canonical(config) + b"\n")
        self.processes["gateway"].stdin.flush()
        self.addresses = {r: v["ip"] for r, v in domains.items()}
        for role in ("red", "blue", "model"):
            for _ in range(300 if role == "model" and self.real_model else 30):
                try:
                    health = self.rpc(role, "health", {})
                    if health.get("ready") is not True:
                        raise EngineError("WORKLOAD_NOT_READY")
                    break
                except EngineError:
                    if (self.snapshot.get("isolation") or {}).get(
                        "enforcement"
                    ) == "FAILED":
                        raise
                    self.check_cancel()
                    time.sleep(0.1)
            else:
                raise EngineError("WORKLOAD_HEALTH_FAILED")
            inspected = self.inspect(self.containers[role])
            controls = effective(
                inspected, health, model_profile=role == "model" and self.real_model
            )
            if (
                inspected["Image"] != self.images[role]
                or len(inspected["NetworkSettings"]["Networks"]) != 1
            ):
                raise EngineError("IMAGE_OR_NETWORK_MISMATCH")
            for workload in self.snapshot["workloads"]:
                if workload["role"] == role:
                    workload["controls"] = controls
                    workload["health"] = "READY"
            self.update()
            if role == "model" and self.campaign:
                if self.real_model and (
                    health.get("provider") != "LOCAL MODEL"
                    or not health.get("readiness_tokens")
                ):
                    raise EngineError("REAL_INFERENCE_READINESS_REQUIRED")
                self.on_model_event(
                    "MODEL_READY", {"duration_ms": health.get("load_duration_ms", 0)}
                )
        gateway = self.inspect(self.containers["gateway"])
        if (
            gateway["HostConfig"]["Sysctls"].get("net.ipv4.ip_forward") != "0"
            or len(gateway["NetworkSettings"]["Networks"]) != 3
        ):
            raise EngineError("GATEWAY_FORWARDING_REJECTED")
        self.metrics()
        self.update("READY")

    def metrics(self):
        if self.assigned_cpus:
            # Retain coarse static ceilings; no new live resource channel for this profile.
            self.update()
            return
        for workload in self.snapshot["workloads"]:
            cid = self.containers[workload["role"]]
            # Docker's stats endpoint is read only here; browser never receives raw output.
            values = (
                self.engine.command(
                    "stats", "--no-stream", "--format", "{{json .}}", cid
                )
                .decode()
                .strip()
            )
            stats = json.loads(values)
            workload["cpu_percent"] = float(stats["CPUPerc"].rstrip("%"))
            amount = stats["MemUsage"].split("/")[0].strip()
            factors = {
                "B": 1,
                "KiB": 1024,
                "MiB": 1024**2,
                "GiB": 1024**3,
                "kB": 1000,
                "MB": 1000**2,
            }
            for unit in sorted(factors, key=len, reverse=True):
                if amount.endswith(unit):
                    workload["memory_bytes"] = int(
                        float(amount[: -len(unit)]) * factors[unit]
                    )
                    break
        self.update()

    def red_case(self, index, correlation):
        return Case.model_validate(
            self.rpc(
                "red", "next", {"index": index, "correlation_id": str(correlation)}
            )
        )

    def campaign_case(self, index, correlation):
        from nexus_api.campaign_schemas import AttackCase

        return AttackCase.model_validate(
            self.rpc(
                "red", "next", {"index": index, "correlation_id": str(correlation)}
            )
        )

    def campaign_guard(self, stage, value):
        result = self.rpc(
            "blue",
            "input" if stage == "input" else "output",
            {"text": value, "input_approved": True},
        )
        if (
            set(result) != {"approved", "action", "text", "reason"}
            or type(result["approved"]) is not bool
            or result["action"] not in {"ALLOW", "TRANSFORM", "BLOCK"}
            or not isinstance(result["text"], str)
            or len(result["text"].encode()) > 4096
        ):
            raise EngineError("GUARD_SCHEMA_REJECTED")
        if result["approved"] != (result["action"] != "BLOCK"):
            raise EngineError("GUARD_SCHEMA_REJECTED")
        return result

    def campaign_inference(self, messages, correlation, *, timeout_ms=None):
        job = str(correlation)
        timeout_ms = timeout_ms or self.budget.model_timeout_ms
        accepted = self.rpc(
            "model",
            "infer_start",
            {
                "job_id": job,
                "messages": messages,
                "timeout_ms": timeout_ms,
            },
        )
        if accepted.get("accepted") is not True:
            raise EngineError("MODEL_REQUEST_REJECTED")
        deadline = time.monotonic() + timeout_ms / 1000 + 2
        while time.monotonic() < deadline:
            self.check_cancel()
            result = self.rpc("model", "infer_poll", {"job_id": job})
            if result.get("done"):
                value = result.get("result", {})
                if value.get("error") == "MODEL_TIMEOUT":
                    raise TimeoutError("MODEL_TIMEOUT")
                if value.get("error"):
                    raise EngineError("MODEL_EXECUTION_ERROR")
                from nexus_api.campaign_results import InferenceResult

                return InferenceResult.model_validate(value).model_dump()
            time.sleep(0.15)
        raise TimeoutError("MODEL_TIMEOUT")

    def input_guard(self, value):
        result = self.rpc("blue", "input", {"text": value, "input_approved": True})
        if type(result.get("approved")) is not bool or not isinstance(
            result.get("text"), str
        ):
            raise EngineError("GUARD_SCHEMA_REJECTED")
        return result["approved"], result["text"]

    def inference(self, value):
        result = self.rpc(
            "model",
            "infer",
            {"text": value, "timeout_ms": self.budget.model_timeout_ms},
        )
        if result.get("error") == "MOCK_MODEL_TIMEOUT":
            raise TimeoutError("MOCK_MODEL_TIMEOUT")
        if result.get("error"):
            raise EngineError("MOCK_MODEL_ERROR")
        if set(result) != {"text"} or not isinstance(result["text"], str):
            raise EngineError("MODEL_SCHEMA_REJECTED")
        return result["text"]

    def output_guard(self, value, input_approved):
        result = self.rpc(
            "blue", "output", {"text": value, "input_approved": input_approved}
        )
        if type(result.get("approved")) is not bool or result.get("text") not in {
            "Mock response: request handled.",
            "Response withheld.",
        }:
            raise EngineError("RELEASE_SCHEMA_REJECTED")
        return result["approved"], result["text"]

    def deliver(self, payload):
        if self.rpc("red", "deliver", payload.model_dump()).get("received") is not True:
            raise EngineError("FINAL_DELIVERY_FAILED")

    def probe_result(
        self, probe_id, source, target, kind, status, observed, expected="DENIED"
    ):
        item = {
            "probe_id": probe_id,
            "source": source,
            "target": target,
            "type": kind,
            "timestamp": datetime.now(UTC).isoformat(),
            "expected": expected,
            "observed": observed,
            "status": status,
            "profile": self.snapshot["profile"]["profile"],
        }
        self.snapshot["probes"].append(item)
        self.update()
        return item

    def probes(self):
        self.update("PROBING")
        # Authenticated health responses prove each direct-connection target is alive.
        for source, target in (
            ("red", "blue"),
            ("red", "model"),
            ("blue", "red"),
            ("blue", "model"),
            ("model", "red"),
            ("model", "blue"),
        ):
            self.check_cancel()
            positive = self.rpc(target, "health", {}).get("ready") is True
            observed = self.rpc(
                source,
                "probe",
                {"kind": "tcp", "target": self.addresses[target], "port": 8080},
            )
            code = observed["errno"]
            status = (
                "PASS"
                if positive
                and code
                in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EACCES, errno.EPERM}
                else "FAIL"
                if code == 0
                else "INCONCLUSIVE"
            )
            self.probe_result(
                f"DIRECT_{source.upper()}_{target.upper()}",
                source,
                target,
                "TCP",
                status,
                f"connect_errno={code}; authenticated_target_health={positive}",
            )
        for kind, target in (
            ("socket", "Docker daemon socket"),
            ("file", "synthetic Blue-only file"),
        ):
            observed = self.rpc("red", "probe", {"kind": kind, "target": "", "port": 0})
            positive = (
                self.rpc("blue", "probe", {"kind": "file", "target": "", "port": 0})[
                    "present"
                ]
                if kind == "file"
                else True
            )
            status = "PASS" if not observed["present"] and positive else "FAIL"
            self.probe_result(
                "SOCKET_ABSENT" if kind == "socket" else "BLUE_FILE_PRIVATE",
                "red",
                target,
                "FILE",
                status,
                f"present={observed['present']}; positive_control={positive}",
            )
        result = self.rpc("red", "probe", {"kind": "resource", "target": "", "port": 0})
        self.probe_result(
            "RESOURCE_PIDS",
            "red",
            "own pids.max=32",
            "CGROUP",
            "PASS" if result["pids_eagain"] else "FAIL",
            f"fork returned EAGAIN={result['pids_eagain']}; memory.max={result['cgroups']['memory.max']}; cpu.max={result['cgroups']['cpu.max']}",
            "ENFORCED",
        )
        self.probe_result(
            "BLOCK_IO",
            "red",
            "block device quota",
            "CGROUP",
            "UNSUPPORTED",
            "No block device exposed or block-I/O claim made",
            "ENFORCED",
        )
        for role in ("red", "blue", "model"):
            for variant in ("wrong_key", "cross_scope", "stale", "replay"):
                observed = self.rpc(role, "auth_probe", {"kind": variant})
                self.probe_result(
                    f"IDENTITY_{role.upper()}_{variant.upper()}",
                    "broker",
                    role,
                    "AUTHENTICATION",
                    "PASS" if observed["positive"] and observed["rejected"] else "FAIL",
                    f"positive_authenticated_health={observed['positive']}; forged_or_replayed_http_status={observed['status']}",
                )
        cpu = self.rpc("red", "probe", {"kind": "cpu", "target": "", "port": 0})
        self.probe_result(
            "RESOURCE_CPU",
            "red",
            "own cpu.max=50000 100000",
            "CGROUP",
            "PASS" if cpu["throttled_periods"] > 0 else "INCONCLUSIVE",
            f"observed throttled periods={cpu['throttled_periods']}",
            "ENFORCED",
        )
        self.witness_probes()
        if self.real_model:
            self.context_probe()
        self.update("READY")
        return self.snapshot["probes"]

    def context_probe(self):
        marker = "NEXUS_CONTEXT_" + uuid4().hex
        clean = [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Reply with the word hello."},
        ]
        # Mandatory infrastructure probes have a separate bounded diagnostic
        # deadline. A tenant's deliberately tiny inference budget must still be
        # tested on tenant cases, rather than aborting these positive controls.
        probe_timeout_ms = 5000
        before = self.campaign_inference(clean, uuid4(), timeout_ms=probe_timeout_ms)
        contaminated = self.campaign_inference(
            [
                {"role": "system", "content": "This is one synthetic case only."},
                {
                    "role": "user",
                    "content": "Remember this test marker for this conversation only: "
                    + marker,
                },
            ],
            uuid4(),
            timeout_ms=probe_timeout_ms,
        )
        after = self.campaign_inference(clean, uuid4(), timeout_ms=probe_timeout_ms)
        absent, equal = marker not in after["text"], before["text"] == after["text"]
        positive = bool(contaminated["prompt_tokens"])
        self.probe_result(
            "FRESH_CASE_CONTEXT",
            "model",
            "independent fresh conversation",
            "PIPELINE",
            "PASS"
            if positive and absent and equal
            else "FAIL"
            if not absent
            else "INCONCLUSIVE",
            f"prior_case_processed={positive}; canary_absent={absent}; identical_clean_response={equal}; prompt_cache=False",
            "ENFORCED",
        )

    def witness_probes(self):
        scope = str(uuid4())
        # The witness is an independent scope for the cross-evaluation probe.
        # Hold its own claim before creating resources so periodic orphan
        # recovery cannot remove a live witness. Standalone adapters without a
        # reconciler may use the default context; the provisioner supplies the
        # same durable claim protocol used for parent evaluations.
        with self.scope_claim(scope) as claim:
            if claim is not None and not claim.acquired:
                raise EngineError("WITNESS_SCOPE_BUSY")
            self._witness_probes(scope)

    def _witness_probes(self, scope):
        process = None
        try:
            net = (
                self.engine.command(
                    "network",
                    "create",
                    "--internal",
                    "--driver",
                    "bridge",
                    "--opt",
                    "com.docker.network.bridge.gateway_mode_ipv4=isolated",
                    "--label",
                    f"io.nexus.owner={self.owner}",
                    "--label",
                    f"io.nexus.evaluation={scope}",
                    "--label",
                    "io.nexus.kind=witness_network",
                    *(
                        ["--label", f"io.nexus.cpu-parent={self.evaluation_id}"]
                        if self.assigned_cpus
                        else []
                    ),
                    f"nexus-witness-{scope[:12]}",
                )
                .decode()
                .strip()
            )
            args = template(
                "model",
                self.images["model"],
                self.owner,
                scope,
                net,
                str(uuid4()),
                assigned_cpus=self.assigned_cpus,
            )
            if self.assigned_cpus:
                args[1:1] = ["--label", f"io.nexus.cpu-parent={self.evaluation_id}"]
            cid = self.engine.command(*args).decode().strip()
            config = {
                "evaluation_id": scope,
                "expires_at": int(time.time()) + 60,
                "key_in": secrets.token_hex(32),
                "key_out": secrets.token_hex(32),
                "artifact": {"mode": "safe"},
                "digest": sha(canonical({"mode": "safe"})),
                "broker": "127.0.0.1",
            }
            process = start(self.engine, cid, config)
            positive = False
            for _ in range(30):
                try:
                    value = self.engine.command(
                        "exec",
                        cid,
                        "python",
                        "-I",
                        "-c",
                        "import socket;s=socket.socket();s.settimeout(.2);print(s.connect_ex(('127.0.0.1',8080))==0);s.close()",
                    )
                    positive = value.decode().strip() == "True"
                    if positive:
                        break
                except EngineError:
                    pass
                time.sleep(0.1)
            if self.assigned_cpus:
                from services.orchestrator.cpu_enforcement import verify

                verify(self.engine, cid, self.owner, scope, self.assigned_cpus)
            inspected = self.inspect(cid)
            address = next(iter(inspected["NetworkSettings"]["Networks"].values()))[
                "IPAddress"
            ]
            observed = self.rpc(
                "red", "probe", {"kind": "tcp", "target": address, "port": 8080}
            )
            status = (
                "PASS"
                if positive
                and observed["errno"]
                in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EACCES, errno.EPERM}
                else "FAIL"
                if observed["connected"]
                else "INCONCLUSIVE"
            )
            self.probe_result(
                "CROSS_EVALUATION",
                "red",
                "independent controlled scope witness",
                "TCP",
                status,
                f"positive_loopback_tcp={positive}; different_scope=True; connect_errno={observed['errno']}",
            )
            # A short-lived synthetic listener on an existing host Docker bridge is the positive control.
            bridge = self.engine.json("network", "inspect", "bridge")[0]["IPAM"][
                "Config"
            ][0]["Gateway"]
            try:
                with socket.socket() as listener:
                    listener.bind((bridge, 0))
                    listener.listen(4)
                    port = listener.getsockname()[1]
                    with socket.create_connection((bridge, port), timeout=0.3):
                        pass
                    denied = self.rpc(
                        "red", "probe", {"kind": "tcp", "target": bridge, "port": port}
                    )
                status = (
                    "PASS"
                    if denied["errno"]
                    in {
                        errno.ENETUNREACH,
                        errno.EHOSTUNREACH,
                        errno.EACCES,
                        errno.EPERM,
                    }
                    else "FAIL"
                    if denied["connected"]
                    else "INCONCLUSIVE"
                )
                self.probe_result(
                    "HOST_EGRESS",
                    "red",
                    "synthetic private host listener",
                    "TCP",
                    status,
                    f"trusted_host_positive_tcp=True; workload_connect_errno={denied['errno']}",
                )
            except OSError:
                self.probe_result(
                    "HOST_EGRESS",
                    "red",
                    "synthetic private host listener",
                    "TCP",
                    "UNSUPPORTED",
                    "Host bridge address unavailable to the provisioner namespace",
                )
            # Dedicated witness may be OOM-killed; production evaluation workloads are not sacrificed.
            result = subprocess.run(
                [
                    "docker",
                    "--host",
                    "unix:///var/run/docker.sock",
                    "exec",
                    cid,
                    "python",
                    "-I",
                    "-c",
                    "x=bytearray(268435456);print(len(x))",
                ],
                capture_output=True,
                check=False,
                timeout=5,
            )
            inspected = self.inspect(cid)
            oom = inspected["State"].get("OOMKilled", False)
            if inspected["State"]["Running"]:
                values = self.engine.command(
                    "exec",
                    cid,
                    "python",
                    "-I",
                    "-c",
                    "import pathlib;print(pathlib.Path('/sys/fs/cgroup/memory.events').read_text())",
                ).decode()
                oom = any(
                    line.startswith("oom_kill ") and int(line.split()[1]) > 0
                    for line in values.splitlines()
                )
            self.probe_result(
                "RESOURCE_MEMORY",
                "model",
                "controlled scope witness memory.max",
                "CGROUP",
                "PASS" if oom and result.returncode != 0 else "FAIL",
                f"oom_kill_observed={oom}; allocator_exit={result.returncode}; limit_bytes=134217728",
                "ENFORCED",
            )
        finally:
            self.engine.cleanup(self.owner, scope)
            if process:
                if process.stdin:
                    process.stdin.close()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()

    def close(self):
        report_failed = False
        try:
            self.update("TEARDOWN")
        except Exception:  # noqa: BLE001 - database/telemetry failure must never prevent cleanup
            report_failed = True
        try:
            cleaned = self.engine.cleanup(self.owner, self.evaluation_id)
        except EngineError:
            cleaned = False
        finally:
            for process in self.processes.values():
                if process.stdin:
                    process.stdin.close()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()
        self.snapshot["container_count"] = (
            0 if cleaned else len(self.snapshot["workloads"])
        )
        self.snapshot["cleanup"] = "VERIFIED" if cleaned else "FAILED"
        for workload in self.snapshot["workloads"]:
            workload["health"] = "REMOVED" if cleaned else "UNKNOWN"
        try:
            self.update("CLEANED" if cleaned else "CLEANUP_FAILED")
        except Exception:  # noqa: BLE001 - preserve actual removal despite unavailable telemetry
            report_failed = True
        if report_failed:
            raise EngineError("RUNTIME_TELEMETRY_FAILED_AFTER_CLEANUP")
        return cleaned
