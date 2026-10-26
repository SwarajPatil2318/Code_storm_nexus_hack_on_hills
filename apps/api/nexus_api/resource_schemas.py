"""Versioned, bounded resource experiment summaries; raw host telemetry stays private."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from nexus_api.schema_base import Strict

Status = Literal["PASS", "FAIL", "INCONCLUSIVE", "UNSUPPORTED"]
Threat = Literal[
    "CPU_CONTENTION",
    "MEMORY_PRESSURE",
    "PID_EXHAUSTION",
    "QUEUE_CONGESTION",
    "STARVATION",
    "TIMING",
    "METADATA",
    "RECOVERY",
    "BLOCK_IO",
    "SCHEDULING",
]


class Distribution(Strict):
    samples: int = Field(ge=0, le=1000)
    failures: int = Field(ge=0, le=1000)
    p50_ms: float | None = Field(default=None, ge=0, le=600000, allow_inf_nan=False)
    p95_ms: float | None = Field(default=None, ge=0, le=600000, allow_inf_nan=False)
    minimum_ms: float | None = Field(default=None, ge=0, le=600000, allow_inf_nan=False)
    maximum_ms: float | None = Field(default=None, ge=0, le=600000, allow_inf_nan=False)

    @model_validator(mode="after")
    def honest_sample(self):
        values = [self.minimum_ms, self.p50_ms, self.maximum_ms]
        successes = self.samples - self.failures
        if (successes == 0 and any(v is not None for v in [*values, self.p95_ms])) or (
            successes > 0 and any(v is None for v in values)
        ):
            raise ValueError("Statistics require observed successful samples")
        if (
            all(v is not None for v in values)
            and not self.minimum_ms <= self.p50_ms <= self.maximum_ms
        ):
            raise ValueError("Median outside observed range")
        if self.failures > self.samples or (
            self.p95_ms is not None and self.samples - self.failures < 20
        ):
            raise ValueError("Insufficient sample size or invalid failure count")
        if (
            self.minimum_ms is not None
            and self.maximum_ms is not None
            and self.minimum_ms > self.maximum_ms
        ):
            raise ValueError("Invalid measurement range")
        return self


class Measurement(Strict):
    metric: Literal[
        "cpu_usage",
        "throttled_periods",
        "throttled_time",
        "memory_peak",
        "oom_kills",
        "pids_peak",
        "fork_rejections",
        "completed",
        "rejected",
        "startup",
        "completion",
        "recovery",
        "jain_index",
        "slowdown",
        "accuracy",
        "false_positives",
        "queue_wait",
        "rejection_latency",
        "confidentiality_checks",
    ]
    value: float = Field(ge=0, le=1e12, allow_inf_nan=False)
    unit: Literal["ms", "us", "bytes", "count", "ratio"]


class ResourceBudget(Strict):
    """Native evaluation budget, or witness budget for the named ceiling/disjoint condition."""

    cpu_cores: float = Field(gt=0, le=4, allow_inf_nan=False)
    memory_bytes: int = Field(ge=16777216, le=2147483648)
    pids: int = Field(ge=1, le=64)
    duration_seconds: int = Field(ge=1, le=300)


class ResourceObservation(Strict):
    experiment_id: UUID
    condition: Literal[
        "ORIGINAL",
        "MATCHED",
        "RESOURCE_CEILING",
        "ADMISSION",
        "SHARED_CPU_TIMING",
        "DISJOINT_CPU_TIMING",
        "FAILURE_RECOVERY",
    ] = "ORIGINAL"
    budget: ResourceBudget | None = None
    threat: Threat
    status: Status
    provenance: Literal["HOST_CGROUP_CAPTURE", "AUTHORIZED_API_TIMING", "APPLICATION_STATE"]
    evaluation_ids: list[UUID] = Field(default_factory=list, max_length=40)
    measurements: list[Measurement] = Field(default_factory=list, max_length=20)
    evidence_digest: str = Field(pattern="^[a-f0-9]{64}$")
    limitations: list[
        Literal[
            "SHARED_KERNEL",
            "TRUSTED_HOST",
            "SMALL_SAMPLE",
            "NO_PHYSICAL_ISOLATION",
            "NO_PENDING_QUEUE",
            "NO_BLOCK_DEVICE",
            "NO_GLOBAL_TELEMETRY",
            "EXPLORATORY_TIMING",
        ]
    ] = Field(min_length=1, max_length=8)


class ResourceEnvironment(Strict):
    logical_cpus: int = Field(ge=1, le=1024)
    total_memory_mib: int = Field(ge=512, le=1048576)
    cgroups: Literal["v2"]
    profile: Literal["rootful", "rootless"]
    model_revision: str = Field(pattern="^[a-f0-9]{40}$")
    model_cpu_limit: float = Field(gt=0, le=2)
    model_memory_mib: int = Field(ge=128, le=1024)
    model_pids: int = Field(ge=1, le=64)
    compared_cpuset_size: int = Field(ge=1, le=4)
    sample_period_ms: int = Field(ge=200, le=5000)


class TimingResult(Strict):
    trials: int = Field(ge=0, le=100)
    active: int = Field(ge=0, le=100)
    inactive: int = Field(ge=0, le=100)
    correct: int = Field(ge=0, le=100)
    false_positives: int = Field(ge=0, le=100)
    positive_control_passed: bool
    negative_control_passed: bool
    status: Status

    @model_validator(mode="after")
    def denominators(self):
        if (
            self.active + self.inactive != self.trials
            or self.correct > self.trials
            or self.false_positives > self.inactive
        ):
            raise ValueError("Invalid timing denominators")
        return self


class ResourceReport(Strict):
    schema_version: Literal["resource-assurance-v1"] = "resource-assurance-v1"
    provenance: Literal["OPERATOR_EXPERIMENT_ATTESTATION"] = "OPERATOR_EXPERIMENT_ATTESTATION"
    status: Status
    environment: ResourceEnvironment
    baseline: Distribution
    stressed: Distribution
    timing: TimingResult
    observations: list[ResourceObservation] = Field(min_length=1, max_length=24)
    raw_evidence_digest: str = Field(pattern="^[a-f0-9]{64}$")
