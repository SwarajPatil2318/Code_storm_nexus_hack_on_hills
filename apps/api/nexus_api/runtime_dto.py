"""Safe runtime projections; never serialize Docker inspect, credentials or private artifacts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from nexus_api.campaign_schemas import ProviderOption
from nexus_api.runtime_schemas import Strict


class RuntimeCapabilities(Strict):
    reduced_interference_available: bool = False
    runtime_owner: UUID | None = None
    images: dict[str, str] = Field(default_factory=dict)
    models: list[ProviderOption] = Field(default_factory=list)
    available: bool
    reason: str = Field(max_length=200)
    profile: str = Field(max_length=64)
    cgroups: str = Field(max_length=32)
    seccomp: bool
    block_io: Literal["UNSUPPORTED"] = "UNSUPPORTED"


class HostProfile(Strict):
    available: bool
    profile: Literal["rootful", "rootless"]
    engine_version: str = Field(max_length=40)
    cgroups: str = Field(max_length=32)
    seccomp: bool
    block_io: Literal["UNSUPPORTED"]


class WorkloadView(Strict):
    role: Literal["red", "blue", "model"]
    container_id: str = Field(pattern="^[a-f0-9]{12}$")
    image_digest: str = Field(pattern="^sha256:[a-f0-9]{64}$")
    network_id: str = Field(pattern="^[a-f0-9]{12}$")
    health: Literal["CREATED", "READY", "REMOVED", "UNKNOWN"]
    controls: dict[str, bool]
    memory_bytes: int | None = Field(default=None, ge=0, le=2147483648)
    cpu_percent: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    memory_limit: Literal[134217728, 1073741824]
    cpu_limit: Literal[0.5, 2]
    pids_limit: Literal[32, 64]
    resource_profile: Literal["mock-128m", "qwen-cpu-1g"] = "mock-128m"


class ProbeView(Strict):
    probe_id: str = Field(pattern="^[A-Z_]{1,64}$")
    source: Literal["broker", "red", "blue", "model"]
    target: str = Field(max_length=120)
    type: Literal["TCP", "FILE", "CGROUP", "PIPELINE", "AUTHENTICATION"]
    timestamp: datetime
    expected: Literal["DENIED", "ENFORCED", "AUTHORIZED"]
    observed: str = Field(max_length=500)
    status: Literal["PASS", "FAIL", "UNSUPPORTED", "INCONCLUSIVE"]
    profile: Literal["rootful", "rootless"]


class IsolationView(Strict):
    security_profile: Literal["STANDARD", "REDUCED_INTERFERENCE"]
    enforcement: Literal["NOT_REQUIRED", "PENDING", "VERIFIED", "FAILED"]
    managed_core_nonoverlap: bool = False
    host_exclusive: Literal[False] = False
    allocation_digest: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    queue_wait_ms: int = Field(default=0, ge=0, le=60000)


class RuntimeSnapshot(Strict):
    isolation: IsolationView | None = None
    state: Literal["PROVISIONING", "READY", "PROBING", "TEARDOWN", "CLEANED", "CLEANUP_FAILED"]
    profile: HostProfile
    workloads: list[WorkloadView] = Field(max_length=3)
    probes: list[ProbeView] = Field(max_length=40)
    cleanup: Literal["PENDING", "VERIFIED", "FAILED"]
    container_count: int = Field(ge=0, le=3)


class RuntimeResponse(Strict):
    evaluation_id: UUID
    execution_mode: str
    snapshot: RuntimeSnapshot | None
    updated_at: datetime | None
    recovery_state: Literal["PENDING", "RUNNING", "RECOVERING", "FINISHED"] | None = None
    cleanup_status: Literal["PENDING", "VERIFIED", "FAILED"] | None = None
    credentials_revoked: bool | None = None
    recovery_reason: str | None = None
