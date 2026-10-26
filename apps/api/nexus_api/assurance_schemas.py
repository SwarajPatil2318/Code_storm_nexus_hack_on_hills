"""Bounded operator experiment attestations; never a claim of host memory erasure."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from nexus_api.schema_base import Strict

Threat = Literal[
    "PROMPT_CONTAMINATION",
    "OUTPUT_CONTAMINATION",
    "RESIDUAL_CONTEXT",
    "KV_CACHE",
    "WRITABLE_STATE",
    "CREDENTIAL_TEARDOWN",
    "RED_BLUE_POLICY",
    "BLUE_RED_PAYLOAD",
    "TELEMETRY",
    "UNAUTHORIZED_ACCESS",
    "CRASH_RESTART",
    "GUARDED_OUTPUT",
]


class AssuranceObservation(Strict):
    threat: Threat
    status: Literal["PASS", "FAIL", "INCONCLUSIVE", "UNSUPPORTED"]
    trials: int = Field(ge=0, le=1000)
    violations: int = Field(ge=0, le=1000)
    evidence_evaluations: list[UUID] = Field(default_factory=list, max_length=20)
    evidence_digest: str = Field(pattern="^[a-f0-9]{64}$")
    scope: Literal[
        "OBSERVED_APPLICATION_BOUNDARY", "CONFIGURATION_AND_PROCESS", "UNPROVEN_PHYSICAL_ERASURE"
    ]

    @model_validator(mode="after")
    def honest_result(self):
        if self.violations > self.trials or (
            self.status == "PASS" and (self.violations or not self.trials)
        ):
            raise ValueError("Invalid experiment outcome")
        return self


class AssuranceMetrics(Strict):
    attack_cases: int = Field(ge=0, le=1000)
    attack_successes: int = Field(ge=0, le=1000)
    input_blocks: int = Field(ge=0, le=1000)
    output_interventions: int = Field(ge=0, le=1000)
    benign_cases: int = Field(ge=0, le=1000)
    benign_completed: int = Field(ge=0, le=1000)
    leakage_trials: int = Field(ge=0, le=1000)
    observed_leaks: int = Field(ge=0, le=1000)
    boundary_checks: int = Field(ge=0, le=1000)
    boundary_violations: int = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def denominators(self):
        for numerator, denominator in [
            (self.attack_successes, self.attack_cases),
            (self.benign_completed, self.benign_cases),
            (self.observed_leaks, self.leakage_trials),
            (self.boundary_violations, self.boundary_checks),
        ]:
            if numerator > denominator:
                raise ValueError("Invalid measurement denominator")
        return self


class AssuranceReport(Strict):
    schema_version: Literal["llm-assurance-v1"] = "llm-assurance-v1"
    provenance: Literal["OPERATOR_EXPERIMENT_ATTESTATION"] = "OPERATOR_EXPERIMENT_ATTESTATION"
    model_id: Literal["Qwen/Qwen2.5-0.5B-Instruct-GGUF"]
    model_revision: str = Field(pattern="^[a-f0-9]{40}$")
    experiment_digest: str = Field(pattern="^[a-f0-9]{64}$")
    metrics: AssuranceMetrics
    observations: list[AssuranceObservation] = Field(min_length=1, max_length=24)
    memory_erasure: Literal["UNPROVEN"] = "UNPROVEN"
