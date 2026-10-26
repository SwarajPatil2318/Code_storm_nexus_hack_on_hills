"""Finite, versioned operator timing study; no host telemetry or private identities."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from nexus_api.resource_schemas import Distribution, Status
from nexus_api.schema_base import Strict


class Interval(Strict):
    low: float = Field(ge=0, le=1, allow_inf_nan=False)
    high: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self):
        if self.low > self.high:
            raise ValueError("Invalid interval")
        return self


class Detector(Strict):
    threshold_ms: float = Field(ge=0, le=600000, allow_inf_nan=False)
    direction: Literal["ABOVE", "BELOW"]
    true_positive: int = Field(ge=0, le=100)
    true_negative: int = Field(ge=0, le=100)
    false_positive: int = Field(ge=0, le=100)
    false_negative: int = Field(ge=0, le=100)
    missing: int = Field(ge=0, le=100)
    accuracy: float = Field(ge=0, le=1, allow_inf_nan=False)
    accuracy_95: Interval
    false_positive_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    false_negative_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    exact_binomial_tail: float = Field(ge=0, le=1, allow_inf_nan=False)
    status: Status

    @model_validator(mode="after")
    def honest_accuracy(self):
        n = (
            self.true_positive
            + self.true_negative
            + self.false_positive
            + self.false_negative
            + self.missing
        )
        if not n or abs(self.accuracy - (self.true_positive + self.true_negative) / n) > 1e-8:
            raise ValueError("Invalid detector denominator")
        return self


class ProfileTiming(Strict):
    security_profile: Literal["STANDARD", "REDUCED_INTERFERENCE"]
    held_out_trials: int = Field(ge=1, le=100)
    active: int = Field(ge=0, le=100)
    inactive: int = Field(ge=0, le=100)
    detector: Detector
    active_latency: Distribution
    inactive_latency: Distribution
    correct_outputs: int = Field(ge=0, le=100)
    effective_affinity_verified: bool
    physical_core_overlap: int | None = Field(default=None, ge=0, le=1024)
    median_completion_ms: float = Field(ge=0, le=3600000, allow_inf_nan=False)
    cases_per_second: float = Field(ge=0, le=100, allow_inf_nan=False)
    queue_wait_ms: int = Field(ge=0, le=60000)
    evaluation_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def matched_counts(self):
        d = self.detector
        if (
            self.active + self.inactive != self.held_out_trials
            or d.true_positive + d.false_negative + d.true_negative + d.false_positive + d.missing
            != self.held_out_trials
            or self.correct_outputs > self.held_out_trials
        ):
            raise ValueError("Invalid trial counts")
        if (
            self.security_profile == "REDUCED_INTERFERENCE"
            and self.effective_affinity_verified
            and self.physical_core_overlap != 0
        ):
            raise ValueError("Unverified physical separation")
        return self


class ResidualTiming(Strict):
    provenance: Literal["POST_HOC_EXPLORATORY"] = "POST_HOC_EXPLORATORY"
    method: Literal["within-block-balanced-permutation-v1"] = "within-block-balanced-permutation-v1"
    permutations: Literal[10000] = 10000
    seed: Literal[1012028] = 1012028
    active_minus_inactive_mean_ms: float = Field(ge=-600000, le=600000, allow_inf_nan=False)
    active_slower_auc: float = Field(ge=0, le=1, allow_inf_nan=False)
    two_sided_permutation_p: float = Field(ge=0, le=1, allow_inf_nan=False)
    status: Literal["FAIL", "INCONCLUSIVE"]


class TimingReport(Strict):
    schema_version: Literal["timing-mitigation-v1"] = "timing-mitigation-v1"
    methodology: Literal["m101-randomized-heldout-v1"] = "m101-randomized-heldout-v1"
    experiment_id: UUID
    provenance: Literal["OPERATOR_EXPERIMENT_ATTESTATION"] = "OPERATOR_EXPERIMENT_ATTESTATION"
    status: Status
    standard: ProfileTiming
    reduced: ProfileTiming
    residual: ResidualTiming | None = None
    positive_control_passed: bool
    negative_control_passed: bool
    historical_m10_bundle_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    raw_evidence_digest: str = Field(pattern="^[a-f0-9]{64}$")
    host_exclusive: Literal[False] = False
    limitations: list[
        Literal[
            "SHARED_KERNEL",
            "TRUSTED_HOST",
            "SMALL_SINGLE_HOST_SAMPLE",
            "CORRELATED_TRIALS",
            "NO_CHANNEL_ELIMINATION",
            "MATCHED_AFFINITY_CONTROL",
            "SYNTHETIC_VICTIM",
            "LEGACY_PROVISIONERS_NOT_COORDINATED",
        ]
    ] = Field(min_length=1, max_length=8)
