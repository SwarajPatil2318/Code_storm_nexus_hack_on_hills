"""Validated measured inference results and role-specific campaign projections."""

from typing import Literal

from pydantic import Field
from sqlalchemy import select

from nexus_api.campaign_schemas import CampaignSummary, CaseOutcome, ModelManifest
from nexus_api.models import ArtifactVersion, CaseRecord
from nexus_api.schema_base import Strict
from nexus_api.versioning import verified_content


class InferenceResult(Strict):
    text: str = Field(max_length=4096)
    duration_ms: int = Field(ge=0, le=90000, strict=True)
    prompt_tokens: int | None = Field(default=None, ge=0, le=2048, strict=True)
    completion_tokens: int | None = Field(default=None, ge=0, le=128, strict=True)
    finish_reason: Literal["stop", "length", "mock"]


def summary(db, evaluation, *, private=False):
    model = ModelManifest.model_validate(
        verified_content(db.get(ArtifactVersion, evaluation.model_version_id))
    )
    corpus = verified_content(db.get(ArtifactVersion, evaluation.red_version_id))
    records = list(
        db.scalars(
            select(CaseRecord)
            .where(CaseRecord.evaluation_id == evaluation.id)
            .order_by(CaseRecord.case_index)
        )
    )
    cases = []
    for record in records:
        data = dict(record.result)
        source = corpus["cases"][record.case_index]
        # Explicit, committed v2 tags only. Never reinterpret historical v1 scores
        # or infer that an arithmetic control represents an adversarial success.
        tags = set(source.get("tags", []))
        data["case_purpose"] = (
            ("attack" if "attack-attempt" in tags else "benign")
            if private
            and corpus["schema_version"] == "campaign-corpus-v2"
            and len(tags & {"attack-attempt", "benign-control"}) == 1
            else "unclassified"
            if private
            else None
        )
        for field in ("objective", "expected_boundary"):
            data[field] = (
                source.get(field) if private and source["case_id"] == record.case_id else None
            )
        if not private:
            for key in (
                "title",
                "attack_input",
                "released_output",
                "criterion",
                "scoring_explanation",
                "attack_category",
                "difficulty",
            ):
                data[key] = None
        cases.append(CaseOutcome.model_validate({**data, "created_at": record.created_at}))
    campaign = evaluation.manifest["campaign"]
    return CampaignSummary(
        evaluation_id=evaluation.id,
        status=evaluation.status,
        blue_approved=evaluation.blue_approved,
        provider=model.provider,
        model_manifest=model,
        arm=campaign["arm"],
        comparison_id=campaign["comparison_id"],
        total_cases=min(len(corpus["cases"]), evaluation.manifest["budget"]["max_cases"]),
        measured_cases=len(cases),
        success=sum(c.attack_outcome == "SUCCESS" for c in cases),
        failure=sum(c.attack_outcome == "FAILURE" for c in cases),
        inconclusive=sum(c.attack_outcome == "INCONCLUSIVE" for c in cases),
        not_evaluated=sum(c.attack_outcome == "NOT_EVALUATED" for c in cases),
        blocked_input=sum(c.input_action == "BLOCK" for c in cases),
        output_interventions=sum(c.output_action in {"TRANSFORM", "BLOCK"} for c in cases),
        runtime_errors=sum(c.model_execution in {"ERROR", "TIMEOUT"} for c in cases),
        total_duration_ms=sum(c.duration_ms for c in cases),
        cases=cases,
    )
