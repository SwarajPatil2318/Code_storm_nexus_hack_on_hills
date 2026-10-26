"""Role/ownership checked synthetic campaigns, private corpus I/O and matched comparisons."""

import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy import select

from nexus_api.access import AccessError
from nexus_api.auth import DB, Identity, deny, require_role
from nexus_api.authorization import evaluation_for, membership_clause
from nexus_api.campaign_corpus import starter_corpus
from nexus_api.campaign_results import summary
from nexus_api.campaign_schemas import (
    AttackCase,
    AttackCorpus,
    BluePolicy,
    CampaignCreate,
    CampaignSummary,
    ComparisonIndex,
    ComparisonResponse,
    CorpusImport,
    CorpusImportFailure,
    ProviderOption,
)
from nexus_api.domain_schemas import EvaluationResponse
from nexus_api.evaluation_api import version_response
from nexus_api.identity_schemas import Role
from nexus_api.lifecycle import emit
from nexus_api.model_catalog import model_manifest
from nexus_api.models import (
    Artifact,
    ArtifactVersion,
    Comparison,
    Evaluation,
    EvaluationMembership,
    VersionGrant,
)
from nexus_api.runtime_client import control
from nexus_api.runtime_schemas import VersionResponse
from nexus_api.versioning import POLICY, canonical, new_version, sha, verified_content

router = APIRouter(tags=["adversarial campaigns"])


@router.get("/campaigns/providers", response_model=list[ProviderOption])
def providers(request: Request, identity: Identity):
    mock = ProviderOption(
        provider="mock",
        model_id="mock-v1",
        revision="1",
        artifact_sha256=None,
        available=True,
        reason="Deterministic MOCK; not real inference",
        resource_profile="mock-128m",
    )
    try:
        capability = control(
            request.app.state.settings, "capabilities", UUID(int=0), identity.user.id
        )
        return [
            mock,
            *[
                ProviderOption.model_validate(m)
                for m in capability.get("models", [])
                if m["provider"] == "local"
            ],
        ]
    except AccessError:
        local = model_manifest("local")
        return [
            mock,
            ProviderOption(
                provider="local",
                model_id=local.model_id,
                revision=local.revision,
                artifact_sha256=local.artifact_sha256,
                available=False,
                reason="Prepare the approved model and start the confined API/provisioner",
                resource_profile=local.resource_profile,
            ),
        ]


@router.get("/campaigns/starter-corpus", response_model=AttackCorpus)
def starter(request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, Role.RED)
    return starter_corpus()


@router.get("/campaigns/versions", response_model=list[VersionResponse])
def versions(request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, Role.RED, Role.BLUE)
    granted = select(VersionGrant.version_id).where(VersionGrant.red_id == identity.user.id)
    query = (
        select(ArtifactVersion)
        .where(
            (
                (ArtifactVersion.owner_id == identity.user.id)
                & ArtifactVersion.kind.in_(["attack", "defence"])
            )
            | (ArtifactVersion.id.in_(granted) if identity.user.role == Role.RED else False)
        )
        .order_by(ArtifactVersion.created_at.desc())
        .limit(200)
    )
    return [
        version_response(v)
        for v in db.scalars(query)
        if verified_content(v).get("schema_version")
        in {"campaign-corpus-v1", "campaign-corpus-v2", "blue-policy-v1"}
    ]


def corpus_for(db, request, identity, version_id):
    require_role(db, request, identity, Role.RED)
    record = db.get(ArtifactVersion, version_id)
    if record is None or record.owner_id != identity.user.id or record.kind != "attack":
        deny(db, request, identity, "not_found", 404)
    try:
        return AttackCorpus.model_validate(verified_content(record))
    except ValueError:
        raise AccessError(409, "incompatible_version", "This is not a campaign corpus") from None


@router.get("/campaigns/corpora/{version_id}/export")
def export_corpus(version_id: UUID, request: Request, db: DB, identity: Identity):
    corpus = corpus_for(db, request, identity, version_id)
    data = b"\n".join(canonical(c.model_dump()) for c in corpus.cases) + b"\n"
    return Response(
        data,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="nexus-synthetic-corpus.jsonl"'},
    )


def duplicate_free(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_FIELD")
        result[key] = value
    return result


@router.post(
    "/campaigns/corpora/import",
    response_model=VersionResponse,
    status_code=201,
    responses={422: {"model": CorpusImportFailure}},
)
def import_corpus(body: CorpusImport, request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, Role.RED)
    try:
        if len(body.jsonl.encode()) > 65536:
            raise ValueError
    except (ValueError, UnicodeError):
        raise AccessError(
            422, "corpus_size", "JSONL must contain at most 65536 UTF-8 bytes"
        ) from None
    cases, errors = [], []
    for index, line in enumerate(body.jsonl.splitlines()):
        if not line.strip():
            continue
        if len(cases) + len(errors) >= 40:
            errors.append({"line": index + 1, "code": "TOO_MANY_CASES"})
            break
        try:
            value = json.loads(
                line,
                object_pairs_hook=duplicate_free,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
            cases.append(AttackCase.model_validate(value))
        except (ValueError, ValidationError, UnicodeError):
            errors.append({"line": index + 1, "code": "INVALID_CASE_SCHEMA"})
    if errors:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_corpus",
                    "message": "No artifact was created; correct the indicated case lines",
                    "request_id": getattr(request.state, "request_id", "unknown"),
                },
                "case_errors": errors,
            },
        )
    try:
        corpus = AttackCorpus(cases=cases)
    except ValueError:
        raise AccessError(
            422, "invalid_corpus", "Provide 1–40 cases with unique case IDs"
        ) from None
    artifact = Artifact(
        owner_id=identity.user.id, name=body.name, kind="attack", private_content=body.jsonl
    )
    db.add(artifact)
    db.flush()
    version = new_version(db, identity.user.id, "attack", corpus.model_dump(), artifact.id)
    db.commit()
    return version_response(version)


def creation_inputs(body, request, db, identity):
    require_role(db, request, identity, Role.RED)
    red, blue = (
        db.get(ArtifactVersion, body.red_version_id),
        db.get(ArtifactVersion, body.blue_version_id),
    )
    if (
        red is None
        or red.owner_id != identity.user.id
        or red.kind != "attack"
        or blue is None
        or blue.kind != "defence"
        or not db.get(VersionGrant, (blue.id, identity.user.id))
    ):
        deny(db, request, identity, "not_found", 404)
    try:
        corpus = AttackCorpus.model_validate(verified_content(red))
        BluePolicy.model_validate(verified_content(blue))
    except ValueError:
        raise AccessError(
            422, "incompatible_versions", "Select campaign corpus and Blue policy versions"
        ) from None
    if (
        body.budget.max_messages < 8 * min(len(corpus.cases), body.budget.max_cases)
        or body.budget.model_timeout_ms > body.budget.case_timeout_ms
    ):
        raise AccessError(
            422,
            "campaign_budget",
            "Budget must cover selected cases and bound inference within each case",
        )
    images = None
    if body.execution_mode == "isolated_docker":
        capability = control(
            request.app.state.settings, "capabilities", UUID(int=0), identity.user.id
        )
        if not capability["available"]:
            raise AccessError(
                503, "runtime_unavailable", "Isolated runtime prerequisites unavailable"
            )
        images = dict(capability["images"])
        if body.provider == "local":
            option = next(
                (
                    m
                    for m in capability.get("models", [])
                    if m["provider"] == "local" and m["available"]
                ),
                None,
            )
            if option is None:
                raise AccessError(
                    503,
                    "model_unavailable",
                    "Prepare the pinned local model and immutable worker image",
                )
            images["model"] = option["image_digest"]
    model = new_version(
        db,
        identity.user.id,
        "model",
        model_manifest(
            body.provider,
            body.generation,
            isolated=body.execution_mode == "isolated_docker",
            mock_mode=body.mock_mode,
        ).model_dump(),
    )
    policy = new_version(db, identity.user.id, "flow_policy", POLICY)
    return red, blue, model, policy, images


def make_campaign(body, db, identity, inputs, *, arm="defended", comparison_id=None):
    red, blue, model, policy, images = inputs
    eid = uuid4()
    manifest = {
        "schema_version": "1.0",
        "security_profile": body.security_profile,
        "execution_mode": body.execution_mode,
        "budget": body.budget.model_dump(),
        "evaluation_id": str(eid),
        "versions": [
            {"kind": v.kind, "version_id": str(v.id), "sha256": v.sha256, "byte_size": v.byte_size}
            for v in (red, blue, model, policy)
        ],
        "model": verified_content(model),
        "campaign": {
            "schema_version": "campaign-v1",
            "arm": arm,
            "comparison_id": str(comparison_id) if comparison_id else None,
            "scoring_version": "deterministic-v2"
            if verified_content(red).get("schema_version") == "campaign-corpus-v2"
            else "deterministic-v1",
        },
    }
    if images is not None:
        manifest["runtime_images"] = images
    evaluation = Evaluation(
        id=eid,
        name=body.name[:145] + f" · {arm}" if comparison_id else body.name,
        owner_id=identity.user.id,
        execution_mode=body.execution_mode,
        status="CREATED",
        red_version_id=red.id,
        blue_version_id=blue.id,
        model_version_id=model.id,
        flow_policy_version_id=policy.id,
        defence_artifact_id=blue.artifact_id,
        manifest=manifest,
        event_sequence=0,
    )
    db.add(evaluation)
    db.flush()
    emit(
        db,
        evaluation,
        "EXECUTION_PROFILE_SELECTED",
        metadata={"security_profile": body.security_profile},
    )
    db.add(EvaluationMembership(evaluation_id=eid, user_id=blue.owner_id))
    emit(
        db,
        evaluation,
        "EVALUATION_CREATED",
        metadata={"status": "CREATED", "execution_mode": evaluation.execution_mode},
    )
    return evaluation


@router.post("/campaigns", response_model=EvaluationResponse, status_code=201)
def create(body: CampaignCreate, request: Request, db: DB, identity: Identity):
    evaluation = make_campaign(body, db, identity, creation_inputs(body, request, db, identity))
    db.commit()
    return evaluation


def campaign_for(evaluation_id, request, db, identity):
    evaluation = evaluation_for(db, request, identity, evaluation_id)
    if not evaluation.manifest or "campaign" not in evaluation.manifest:
        raise AccessError(409, "not_campaign", "Select a campaign evaluation")
    return evaluation


@router.get("/campaigns/{evaluation_id}", response_model=CampaignSummary)
def detail(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = campaign_for(evaluation_id, request, db, identity)
    return summary(
        db,
        evaluation,
        private=identity.user.role == Role.RED and evaluation.owner_id == identity.user.id,
    )


@router.post("/comparisons", response_model=ComparisonResponse, status_code=201)
def create_comparison(body: CampaignCreate, request: Request, db: DB, identity: Identity):
    inputs = creation_inputs(body, request, db, identity)
    comparison_id = uuid4()
    baseline = make_campaign(
        body, db, identity, inputs, arm="baseline", comparison_id=comparison_id
    )
    defended = make_campaign(
        body, db, identity, inputs, arm="defended", comparison_id=comparison_id
    )
    manifest = {
        field: str(getattr(baseline, field))
        for field in (
            "red_version_id",
            "blue_version_id",
            "model_version_id",
            "flow_policy_version_id",
        )
    }
    manifest.update(
        {
            "schema_version": "comparison-v1",
            "security_profile": body.security_profile,
            "budget": body.budget.model_dump(),
            "model": verified_content(inputs[2]),
            "runtime_images": inputs[4],
            "scoring_version": baseline.manifest["campaign"]["scoring_version"],
            "context_policy": "fresh_case_explicit_turns_no_prompt_cache",
            "baseline_id": str(baseline.id),
            "defended_id": str(defended.id),
        }
    )
    comparison = Comparison(
        id=comparison_id,
        owner_id=identity.user.id,
        baseline_id=baseline.id,
        defended_id=defended.id,
        manifest=manifest,
        manifest_digest=sha(canonical(manifest)),
    )
    db.add(comparison)
    db.commit()
    return comparison_response(comparison, request, db, identity)


def comparison_response(comparison, request, db, identity):
    baseline = campaign_for(comparison.baseline_id, request, db, identity)
    defended = campaign_for(comparison.defended_id, request, db, identity)
    private = identity.user.role == Role.RED and comparison.owner_id == identity.user.id
    a, b = summary(db, baseline, private=private), summary(db, defended, private=private)
    conclusion = "PENDING"
    if a.status in {"FAILED", "CANCELLED", "DESTROYED"} or b.status in {
        "FAILED",
        "CANCELLED",
        "DESTROYED",
    }:
        conclusion = "NOT_COMPARABLE"
    elif a.status == b.status == "COMPLETED":
        comparable = (
            a.measured_cases == b.measured_cases == a.total_cases == b.total_cases
            and not (
                a.inconclusive
                + a.not_evaluated
                + b.inconclusive
                + b.not_evaluated
                + a.runtime_errors
                + b.runtime_errors
            )
            and [c.case_id for c in a.cases] == [c.case_id for c in b.cases]
        )
        conclusion = (
            ("LOWER_OBSERVED_SUCCESS" if b.success < a.success else "NO_MEASURED_IMPROVEMENT")
            if comparable
            else "NOT_COMPARABLE"
        )
    return ComparisonResponse(
        id=comparison.id,
        baseline_id=baseline.id,
        defended_id=defended.id,
        manifest=comparison.manifest,
        manifest_digest=comparison.manifest_digest,
        baseline=a,
        defended=b,
        conclusion=conclusion,
    )


@router.get("/comparisons", response_model=list[ComparisonIndex])
def list_comparisons(request: Request, db: DB, identity: Identity):
    authorized = select(Evaluation.id).where(membership_clause(identity.user.id))
    query = (
        select(Comparison)
        .where(Comparison.baseline_id.in_(authorized), Comparison.defended_id.in_(authorized))
        .order_by(Comparison.created_at.desc())
        .limit(50)
    )
    return [
        ComparisonIndex(
            id=c.id,
            name=db.get(Evaluation, c.baseline_id).name.removesuffix(" · baseline"),
            baseline_id=c.baseline_id,
            defended_id=c.defended_id,
        )
        for c in db.scalars(query)
    ]


@router.get("/comparisons/{comparison_id}", response_model=ComparisonResponse)
def comparison_detail(comparison_id: UUID, request: Request, db: DB, identity: Identity):
    comparison = db.get(Comparison, comparison_id)
    if comparison is None:
        deny(db, request, identity, "not_found", 404)
    return comparison_response(comparison, request, db, identity)
