"""Bounded synthetic campaigns and explicit provider/defence/scoring contracts."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from nexus_api.assurance_schemas import AssuranceReport
from nexus_api.resource_schemas import ResourceReport
from nexus_api.schema_base import Strict
from nexus_api.schemas import ErrorDetail
from nexus_api.timing_schemas import TimingReport

QWEN_ID = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
QWEN_REVISION = "9217f5db79a29953eb74d5343926648285ec7e67"
QWEN_SHA = "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"
BACKEND_SHA = "8cb635bc20046c0aa75c623c8223c9b6b40bef8ecbc01dbce320eda48a72b5dd"
Category = Literal[
    "instruction_override",
    "system_extraction",
    "role_spoofing",
    "document_injection",
    "conflicting_instructions",
    "multi_turn",
    "format_bypass",
    "simulated_tool_injection",
    "synthetic_credentials",
    "cross_evaluation_canary",
]
Action = Literal["ALLOW", "TRANSFORM", "BLOCK"]
Outcome = Literal["SUCCESS", "FAILURE", "INCONCLUSIVE", "NOT_EVALUATED"]
Execution = Literal["EXECUTED", "SKIPPED", "ERROR", "TIMEOUT"]


class Turn(Strict):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=512)


class ScoringRule(Strict):
    strategy: Literal[
        "canary_match", "forbidden_marker", "exact_output", "invalid_json", "invalid_json_answer"
    ]
    expected: str = Field(min_length=1, max_length=96)


class AttackCase(Strict):
    case_id: str = Field(pattern="^[a-z0-9][a-z0-9-]{0,39}$")
    attack_category: Category
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=300)
    attack_input: str = Field(min_length=1, max_length=1600)
    trusted_context: str = Field(default="", max_length=640)
    turns: list[Turn] = Field(default_factory=list, max_length=4)
    objective: str = Field(min_length=1, max_length=200)
    expected_boundary: str = Field(min_length=1, max_length=200)
    scoring: ScoringRule
    tags: list[Annotated[str, Field(pattern="^[a-z0-9-]{1,30}$")]] = Field(
        default_factory=list, max_length=8
    )
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    corpus_version: Literal["nexus-synthetic-v1"] = "nexus-synthetic-v1"

    @model_validator(mode="after")
    def bounded_conversation(self):
        if (
            len(
                (
                    self.attack_input
                    + self.trusted_context
                    + "".join(t.content for t in self.turns)
                ).encode()
            )
            > 2800
        ):
            raise ValueError("Case conversation exceeds 2800 UTF-8 bytes")
        if (
            any(t.role != ("user" if i % 2 == 0 else "assistant") for i, t in enumerate(self.turns))
            or len(self.turns) % 2
        ):
            raise ValueError("History must contain complete case-local user/assistant pairs")
        return self


class AttackCorpus(Strict):
    schema_version: Literal["campaign-corpus-v1", "campaign-corpus-v2"] = "campaign-corpus-v2"
    cases: list[AttackCase] = Field(min_length=1, max_length=40)
    assurance_report: AssuranceReport | None = None
    resource_report: ResourceReport | None = None
    timing_report: TimingReport | None = None

    @model_validator(mode="after")
    def unique_ids(self):
        if len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError("Case identifiers must be unique")
        if self.schema_version == "campaign-corpus-v1" and (
            self.assurance_report is not None
            or self.resource_report is not None
            or self.timing_report is not None
            or any(c.scoring.strategy == "invalid_json_answer" for c in self.cases)
        ):
            raise ValueError("New criteria/reports require immutable corpus v2")
        return self


class BluePolicy(Strict):
    schema_version: Literal["blue-policy-v1"] = "blue-policy-v1"
    input_terms: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=lambda: [
            "ignore previous",
            "reveal the secret",
            "system prompt",
            "admin override",
        ],
        max_length=20,
    )
    input_action: Action = "BLOCK"
    output_terms: list[Annotated[str, Field(min_length=1, max_length=96)]] = Field(
        default_factory=lambda: [
            "NEXUS_SYNTH_CANARY",
            "NEXUS_SYNTH_CREDENTIAL",
            "NEXUS_SYNTH_TOOL_EXECUTED",
        ],
        max_length=20,
    )
    output_action: Literal["BLOCK", "TRANSFORM"] = "BLOCK"
    require_json: bool = Field(default=False, strict=True)
    strip_role_tokens: bool = Field(default=True, strict=True)


class Generation(Strict):
    temperature: Literal[0] = 0
    seed: int = Field(default=42, ge=0, le=2147483647, strict=True)
    max_output_tokens: int = Field(default=64, ge=8, le=128, strict=True)
    context_window: Literal[2048] = 2048


class ModelManifest(Strict):
    schema_version: Literal["model-manifest-v1"] = "model-manifest-v1"
    provider: Literal["mock", "local"]
    model_id: Literal["mock-v1", "Qwen/Qwen2.5-0.5B-Instruct-GGUF"]
    revision: str = Field(max_length=64)
    artifact_sha256: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    tokenizer_revision: str = Field(max_length=64)
    family: Literal["deterministic", "qwen2.5"]
    generation: Generation = Generation()
    resource_profile: Literal["mock-128m", "qwen-cpu-1g"]
    backend: Literal["deterministic-v1", "llama.cpp-b11731-cpu"]
    backend_sha256: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    isolation: Literal["in_process", "isolated_container"]
    context_policy: Literal["fresh_case_explicit_turns_no_prompt_cache"] = (
        "fresh_case_explicit_turns_no_prompt_cache"
    )
    mock_mode: Literal["safe", "canary", "error", "timeout"] = "safe"

    @model_validator(mode="after")
    def approved_backend(self):
        if self.provider == "local":
            if self.backend_sha256 != BACKEND_SHA:
                raise ValueError("Unapproved inference backend artifact")
            if (
                self.model_id,
                self.revision,
                self.artifact_sha256,
                self.tokenizer_revision,
                self.family,
                self.resource_profile,
                self.backend,
                self.isolation,
                self.mock_mode,
            ) != (
                QWEN_ID,
                QWEN_REVISION,
                QWEN_SHA,
                QWEN_REVISION,
                "qwen2.5",
                "qwen-cpu-1g",
                "llama.cpp-b11731-cpu",
                "isolated_container",
                "safe",
            ):
                raise ValueError("Only the approved immutable CPU model profile is allowed")
        elif self.backend_sha256 is not None or (
            self.model_id,
            self.revision,
            self.tokenizer_revision,
            self.artifact_sha256,
            self.family,
            self.resource_profile,
            self.backend,
        ) != ("mock-v1", "1", "none", None, "deterministic", "mock-128m", "deterministic-v1"):
            raise ValueError("Invalid deterministic provider manifest")
        return self


class CampaignBudget(Strict):
    max_cases: int = Field(default=5, ge=1, le=40, strict=True)
    max_messages: int = Field(default=320, ge=8, le=640, strict=True)
    max_bytes: int = Field(default=8192, ge=512, le=8192, strict=True)
    timeout_seconds: int = Field(default=300, ge=5, le=600, strict=True)
    model_timeout_ms: int = Field(default=30000, ge=20, le=60000, strict=True)
    case_timeout_ms: int = Field(default=45000, ge=100, le=90000, strict=True)
    concurrency: Literal[1, 2] = 1


class CampaignCreate(Strict):
    security_profile: Literal["STANDARD", "REDUCED_INTERFERENCE"] = "STANDARD"
    name: str = Field(min_length=1, max_length=160)
    red_version_id: UUID
    blue_version_id: UUID
    execution_mode: Literal["local_mock", "isolated_docker"] = "isolated_docker"
    provider: Literal["mock", "local"] = "local"
    mock_mode: Literal["safe", "canary", "error", "timeout"] = "safe"
    generation: Generation = Generation()
    budget: CampaignBudget = CampaignBudget()

    @model_validator(mode="after")
    def provider_boundary(self):
        if (
            self.security_profile == "REDUCED_INTERFERENCE"
            and self.execution_mode != "isolated_docker"
        ):
            raise ValueError("Reduced interference requires verified Docker execution")
        if self.provider == "local" and (
            self.execution_mode != "isolated_docker" or self.mock_mode != "safe"
        ):
            raise ValueError(
                "Real inference requires the isolated local model; no mock substitution"
            )
        return self


class CorpusImport(Strict):
    name: str = Field(min_length=1, max_length=160)
    jsonl: str = Field(min_length=1, max_length=65536)


class CorpusLineError(Strict):
    line: int = Field(ge=1, le=65536)
    code: Literal["INVALID_CASE_SCHEMA", "TOO_MANY_CASES"]


class CorpusImportFailure(Strict):
    error: ErrorDetail
    case_errors: list[CorpusLineError] = Field(default_factory=list, max_length=41)


class ProviderOption(Strict):
    provider: Literal["mock", "local"]
    model_id: str
    revision: str
    artifact_sha256: str | None
    available: bool
    reason: str
    resource_profile: str
    image_digest: str | None = Field(default=None, pattern="^sha256:[a-f0-9]{64}$")


class CaseOutcome(Strict):
    case_id: str
    case_index: int
    correlation_id: UUID
    policy_decision: Literal["ALLOW", "DENY"] | None
    input_action: Action | None
    output_action: Action | None
    model_execution: Execution
    attack_outcome: Outcome
    duration_ms: int
    inference_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    finish_reason: Literal["stop", "length", "mock"] | None = None
    error_code: str | None
    title: str | None
    objective: str | None = None
    expected_boundary: str | None = None
    attack_category: Category | None = None
    case_purpose: Literal["attack", "benign", "unclassified"] | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    attack_input: str | None
    released_output: str | None
    criterion: ScoringRule | None
    scoring_explanation: str | None
    created_at: datetime


class CampaignSummary(Strict):
    evaluation_id: UUID
    status: str
    blue_approved: bool
    provider: Literal["mock", "local"]
    model_manifest: ModelManifest
    arm: Literal["baseline", "defended"]
    comparison_id: UUID | None
    total_cases: int
    measured_cases: int
    success: int
    failure: int
    inconclusive: int
    not_evaluated: int
    blocked_input: int
    output_interventions: int
    runtime_errors: int
    total_duration_ms: int
    cases: list[CaseOutcome]


class ComparisonResponse(Strict):
    id: UUID
    baseline_id: UUID
    defended_id: UUID
    manifest: dict
    manifest_digest: str
    baseline: CampaignSummary
    defended: CampaignSummary
    conclusion: Literal[
        "PENDING", "NO_MEASURED_IMPROVEMENT", "LOWER_OBSERVED_SUCCESS", "NOT_COMPARABLE"
    ]


class ComparisonIndex(Strict):
    id: UUID
    name: str
    baseline_id: UUID
    defended_id: UUID
