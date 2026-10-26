"""Operator lifecycle API. No endpoint accepts service messages, forwarding URLs or caller roles."""

from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Request
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from nexus_api.access import AccessError
from nexus_api.auth import DB, Identity, deny, require_role
from nexus_api.authorization import artifact_for, artifact_is_sealed, evaluation_for
from nexus_api.campaign_schemas import AttackCorpus, BluePolicy
from nexus_api.domain_schemas import EvaluationResponse
from nexus_api.execution import run_evaluation
from nexus_api.identity_schemas import Role
from nexus_api.lifecycle import bindings, emit, locked, transition, verify_evaluation
from nexus_api.models import (
    ArtifactVersion,
    Evaluation,
    EvaluationMembership,
    EvaluationResult,
    User,
    VersionGrant,
)
from nexus_api.runtime_schemas import (
    AuditorCreate,
    Corpus,
    EvaluationCreate,
    GrantCreate,
    GrantResponse,
    GuardConfig,
    ManifestResponse,
    ReleasedResult,
    VersionCreate,
    VersionResponse,
)
from nexus_api.versioning import POLICY, canonical, new_version, sha, verified_content

router = APIRouter(tags=["local application evaluation"])


def version_response(record):
    return VersionResponse(
        version_id=record.id,
        artifact_id=record.artifact_id,
        owner_id=record.owner_id,
        domain=record.domain,
        kind=record.kind,
        sha256=record.sha256,
        byte_size=record.byte_size,
        content_ref=record.content_ref,
        created_at=record.created_at,
        visibility=record.visibility,
    )


@router.post("/artifacts/{artifact_id}/versions", response_model=VersionResponse, status_code=201)
def create_version(
    artifact_id: UUID, body: VersionCreate, request: Request, db: DB, identity: Identity
):
    artifact = artifact_for(db, request, identity, artifact_id)
    if artifact_is_sealed(db, artifact):
        deny(db, request, identity, "sealed_artifact_immutable")
    expected = (Corpus, AttackCorpus) if artifact.kind == "attack" else (GuardConfig, BluePolicy)
    if not isinstance(body.content, expected):
        raise AccessError(422, "invalid_version", "Version content has the wrong schema")
    record = new_version(
        db, identity.user.id, artifact.kind, body.content.model_dump(mode="json"), artifact.id
    )
    db.commit()
    return version_response(record)


@router.get("/versions", response_model=list[VersionResponse])
def versions(request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, Role.RED, Role.BLUE)
    own = (ArtifactVersion.owner_id == identity.user.id) & ArtifactVersion.kind.in_(
        ["attack", "defence"]
    )
    granted = (
        ArtifactVersion.id.in_(
            select(VersionGrant.version_id).where(VersionGrant.red_id == identity.user.id)
        )
        if identity.user.role == Role.RED
        else False
    )
    return [
        version_response(v)
        for v in db.scalars(
            select(ArtifactVersion)
            .where(or_(own, granted))
            .order_by(ArtifactVersion.created_at.desc())
            .limit(200)
        )
    ]


@router.post("/versions/{version_id}/grants", response_model=GrantResponse)
def grant(version_id: UUID, body: GrantCreate, request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, Role.BLUE)
    version = db.get(ArtifactVersion, version_id)
    red = db.scalar(
        select(User).where(
            User.email == body.red_email.lower(), User.role == Role.RED, User.is_active.is_(True)
        )
    )
    if not version or version.owner_id != identity.user.id or version.kind != "defence" or not red:
        deny(db, request, identity, "not_found", 404)
    db.execute(
        insert(VersionGrant).values(version_id=version.id, red_id=red.id).on_conflict_do_nothing()
    )
    db.commit()
    return GrantResponse(version_id=version.id, red_id=red.id)


@router.post("/evaluations", response_model=EvaluationResponse, status_code=201)
def create_evaluation(body: EvaluationCreate, request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, Role.RED)
    if body.execution_mode == "isolated_docker":
        from nexus_api.runtime_client import control

        capability = control(
            request.app.state.settings, "capabilities", UUID(int=0), identity.user.id
        )
        if not capability["available"]:
            raise AccessError(
                503, "isolated_unavailable", "Required isolated runtime controls are unavailable"
            )
    red, blue = (
        db.get(ArtifactVersion, body.red_version_id),
        db.get(ArtifactVersion, body.blue_version_id),
    )
    if (
        not red
        or red.kind != "attack"
        or red.owner_id != identity.user.id
        or not blue
        or blue.kind != "defence"
        or not db.get(VersionGrant, (blue.id, identity.user.id))
    ):
        deny(db, request, identity, "not_found", 404)
    try:
        corpus = Corpus.model_validate(verified_content(red))
        GuardConfig.model_validate(verified_content(blue))
    except ValueError:
        raise AccessError(
            422, "incompatible_versions", "Use Attack Lab for campaign corpus/defence versions"
        ) from None
    if len(corpus.cases) > body.budget.max_cases:
        raise AccessError(422, "case_budget", "Corpus exceeds the selected case budget")
    model = new_version(
        db, identity.user.id, "model", {"adapter": "mock-v1", "mode": body.model_mode}
    )
    policy = new_version(db, identity.user.id, "flow_policy", POLICY)
    evaluation = Evaluation(
        id=uuid4(),
        owner_id=identity.user.id,
        name=body.name.strip(),
        execution_mode=body.execution_mode,
        status="CREATED",
        red_version_id=red.id,
        blue_version_id=blue.id,
        model_version_id=model.id,
        flow_policy_version_id=policy.id,
        defence_artifact_id=blue.artifact_id,
        event_sequence=0,
        manifest={
            "schema_version": "1.0",
            "execution_mode": body.execution_mode,
            "budget": body.budget.model_dump(),
            "evaluation_id": "",
            "versions": [],
        },
    )
    evaluation.manifest = {
        **evaluation.manifest,
        "evaluation_id": str(evaluation.id),
        "versions": [
            {"kind": v.kind, "version_id": str(v.id), "sha256": v.sha256, "byte_size": v.byte_size}
            for v in (red, blue, model, policy)
        ],
    }
    if body.execution_mode == "isolated_docker":
        evaluation.manifest = {**evaluation.manifest, "runtime_images": capability["images"]}
    db.add(evaluation)
    db.flush()
    db.add(EvaluationMembership(evaluation_id=evaluation.id, user_id=blue.owner_id))
    emit(
        db,
        evaluation,
        "EVALUATION_CREATED",
        metadata={"status": "CREATED", "execution_mode": evaluation.execution_mode},
    )
    db.commit()
    return evaluation


def local_evaluation(db, request, identity, evaluation_id):
    evaluation_for(db, request, identity, evaluation_id)
    evaluation = locked(db, evaluation_id)
    if evaluation.execution_mode not in {"local_mock", "isolated_docker"}:
        raise AccessError(409, "legacy_evaluation", "Legacy metadata cannot execute")
    return evaluation


def owner(db, request, identity, evaluation):
    if identity.user.role != Role.RED or identity.user.id != evaluation.owner_id:
        deny(db, request, identity)


@router.get("/evaluations/{evaluation_id}/manifest", response_model=ManifestResponse)
def manifest(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = local_evaluation(db, request, identity, evaluation_id)
    return ManifestResponse(
        evaluation_id=evaluation.id,
        status=evaluation.status,
        execution_mode=evaluation.execution_mode,
        manifest_digest=evaluation.manifest_digest,
        manifest=evaluation.manifest,
        blue_approved=evaluation.blue_approved,
    )


@router.post("/evaluations/{evaluation_id}/commit", response_model=EvaluationResponse)
def commit(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = local_evaluation(db, request, identity, evaluation_id)
    owner(db, request, identity, evaluation)
    transition(db, evaluation, "COMMITTED")
    for version in bindings(db, evaluation):
        verified_content(version)
    evaluation.manifest_digest = sha(canonical(evaluation.manifest))
    db.commit()
    return evaluation


@router.post("/evaluations/{evaluation_id}/approve", response_model=EvaluationResponse)
def approve(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = local_evaluation(db, request, identity, evaluation_id)
    blue = db.get(ArtifactVersion, evaluation.blue_version_id)
    if identity.user.role != Role.BLUE or blue.owner_id != identity.user.id:
        deny(db, request, identity)
    if evaluation.status != "COMMITTED" or evaluation.blue_approved:
        raise AccessError(409, "invalid_transition", "Approval requires an unapproved commitment")
    verify_evaluation(db, evaluation)
    evaluation.blue_approved = True
    emit(db, evaluation, "BLUE_APPROVED")
    db.commit()
    return evaluation


@router.post("/evaluations/{evaluation_id}/seal", response_model=EvaluationResponse)
def seal(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = local_evaluation(db, request, identity, evaluation_id)
    owner(db, request, identity, evaluation)
    if not evaluation.blue_approved:
        raise AccessError(409, "approval_required", "Blue must approve the committed manifest")
    verify_evaluation(db, evaluation)
    transition(db, evaluation, "SEALED")
    db.commit()
    return evaluation


@router.post(
    "/evaluations/{evaluation_id}/start", response_model=EvaluationResponse, status_code=202
)
def start(
    evaluation_id: UUID, request: Request, background: BackgroundTasks, db: DB, identity: Identity
):
    # Serialize global capacity checks too; fixed local workers have no unbounded pending queue.
    db.execute(text("SELECT pg_advisory_xact_lock(73629301)"))
    evaluation = local_evaluation(db, request, identity, evaluation_id)
    owner(db, request, identity, evaluation)
    if evaluation.status != "SEALED":
        raise AccessError(409, "invalid_transition", "Start requires a sealed evaluation")
    try:
        verify_evaluation(db, evaluation)
    except (ValueError, TypeError, KeyError):
        transition(db, evaluation, "FAILED")
        emit(db, evaluation, "SECURITY_PROBE_FAILED", metadata={"reason_code": "DIGEST_MISMATCH"})
        db.commit()
        raise AccessError(409, "integrity_failure", "Commitment verification failed") from None
    active = db.scalar(
        select(func.count())
        .select_from(Evaluation)
        .where(
            Evaluation.execution_mode.in_(["local_mock", "isolated_docker"]),
            Evaluation.status.in_(["PROVISIONING", "RUNNING", "FINALIZING"]),
        )
    )
    selected_profile = evaluation.manifest.get("security_profile", "STANDARD")
    if active >= (4 if selected_profile == "REDUCED_INTERFERENCE" else 2):
        raise AccessError(429, "runtime_capacity", "Local execution capacity is busy")
    if evaluation.execution_mode == "isolated_docker":
        from nexus_api.runtime_client import control

        capability = control(
            request.app.state.settings, "capabilities", UUID(int=0), identity.user.id
        )
        if not capability["available"]:
            raise AccessError(503, "isolated_unavailable", "Isolated runtime is unavailable")
        if selected_profile == "REDUCED_INTERFERENCE" and not capability.get(
            "reduced_interference_available"
        ):
            raise AccessError(
                503, "profile_unsupported", "Reduced interference requirements are unavailable"
            )
    transition(db, evaluation, "PROVISIONING")
    from nexus_api.recovery import intent

    intent(
        db,
        evaluation,
        capability.get("runtime_owner") if evaluation.execution_mode == "isolated_docker" else None,
    )
    db.commit()
    if evaluation.execution_mode == "isolated_docker":
        try:
            control(request.app.state.settings, "run", evaluation.id, identity.user.id)
        except AccessError:
            # A timeout may be a lost acknowledgement after successful acceptance.
            # Durable intent is reconciled by its owner; never fail healthy work here.
            raise
    else:
        background.add_task(run_evaluation, request.app.state.engine, evaluation.id)
    return evaluation


@router.post("/evaluations/{evaluation_id}/cancel", response_model=EvaluationResponse)
def cancel(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = local_evaluation(db, request, identity, evaluation_id)
    blue = db.get(ArtifactVersion, evaluation.blue_version_id)
    if not (
        (identity.user.role == Role.RED and identity.user.id == evaluation.owner_id)
        or (identity.user.role == Role.BLUE and identity.user.id == blue.owner_id)
    ):
        deny(db, request, identity)
    transition(db, evaluation, "CANCELLED")
    db.commit()
    return evaluation


@router.post("/evaluations/{evaluation_id}/destroy", response_model=EvaluationResponse)
def destroy(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = local_evaluation(db, request, identity, evaluation_id)
    owner(db, request, identity, evaluation)
    if evaluation.execution_mode == "isolated_docker":
        from nexus_api.runtime_client import control

        db.rollback()  # The trusted service owns the cleanup/terminal-state transaction.
        control(request.app.state.settings, "destroy", evaluation_id, identity.user.id)
        db.expire_all()
        return db.get(Evaluation, evaluation_id)
    transition(db, evaluation, "DESTROYED")
    db.commit()
    return evaluation


@router.get("/evaluations/{evaluation_id}/released-result", response_model=ReleasedResult)
def released(evaluation_id: UUID, request: Request, db: DB, identity: Identity):
    evaluation = local_evaluation(db, request, identity, evaluation_id)
    owner(db, request, identity, evaluation)
    if "campaign" in evaluation.manifest:
        raise AccessError(409, "campaign_result", "Inspect the authorized campaign case outcomes")
    result = db.scalar(
        select(EvaluationResult).where(EvaluationResult.evaluation_id == evaluation_id)
    )
    if result is None:
        raise AccessError(404, "not_found", "No released result is available")
    return ReleasedResult(
        evaluation_id=evaluation_id, results=result.summary.get("released_results", [])
    )


@router.post("/evaluations/{evaluation_id}/auditor", status_code=204)
def add_auditor(
    evaluation_id: UUID, body: AuditorCreate, request: Request, db: DB, identity: Identity
):
    evaluation = local_evaluation(db, request, identity, evaluation_id)
    owner(db, request, identity, evaluation)
    auditor = db.scalar(
        select(User).where(
            User.email == body.email.lower(), User.role == Role.AUDITOR, User.is_active.is_(True)
        )
    )
    if not auditor:
        deny(db, request, identity, "not_found", 404)
    db.execute(
        insert(EvaluationMembership)
        .values(evaluation_id=evaluation.id, user_id=auditor.id)
        .on_conflict_do_nothing()
    )
    emit(db, evaluation, "ACCESS_GRANTED", metadata={"reason_code": "AUDITOR_METADATA_MEMBERSHIP"})
    db.commit()
