"""Separate authenticated provisioner process; fixed operations, bounded jobs, labelled cleanup."""

import fcntl
import hashlib
import hmac
import json
import os
import secrets
import signal
import socket
import socketserver
import struct
import threading
import time
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import UUID, uuid4

from nexus_api.access import AccessError
from nexus_api.campaign_schemas import CampaignBudget
from nexus_api.config import Settings
from nexus_api.database import SCHEMA_REVISION, make_engine
from nexus_api.database_security import validate_runtime
from nexus_api.execution import run_evaluation
from nexus_api.lifecycle import emit, locked, transition, verify_evaluation
from nexus_api.logging import configure_logging
from nexus_api.model_catalog import model_manifest
from nexus_api.models import EvaluationJob, RuntimeRecord, User
from nexus_api.recovery import ACTIVE, ExecutionClaim, intent, interrupted
from nexus_api.runtime_dto import RuntimeSnapshot
from nexus_api.runtime_schemas import Budget, Strict
from nexus_api.versioning import canonical
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from services.orchestrator.cpu_allocation import AllocationManager, CapacityError
from services.orchestrator.cpu_topology import discover
from services.orchestrator.engine import (
    CONFIG_FILE,
    STATE,
    DockerEngine,
    EngineError,
    image_id,
)
from services.orchestrator.model_registry import approved_images, local_runtime
from services.orchestrator.runtime import DockerRuntimeAdapter


class ControlRequest(Strict):
    operation: str = Field(pattern="^(capabilities|run|probes|destroy)$")
    evaluation_id: UUID
    actor_id: UUID
    nonce: str = Field(pattern="^[a-f0-9]{32}$")
    timestamp: int = Field(strict=True)


class Provisioner:
    def __init__(self, engine, owner, images):
        self.engine, self.owner, self.images = engine, owner, images
        self.docker = DockerEngine()
        self.allocations = AllocationManager(self.docker)
        self.active = set()
        self.mutex = threading.Lock()
        self.seen = {}
        self.stopping = threading.Event()
        self.lock_dir = STATE / "job-locks"

    def report(self, eid, claim=None):
        previous = [0]
        last_isolation = [None]

        def record(snapshot):
            if claim:
                claim.check()
            safe = RuntimeSnapshot.model_validate(snapshot).model_dump(mode="json")
            with Session(self.engine) as db:
                evaluation = locked(db, eid)
                runtime = db.get(RuntimeRecord, eid)
                if runtime is None:
                    runtime = RuntimeRecord(evaluation_id=eid, snapshot=safe)
                    db.add(runtime)
                else:
                    runtime.snapshot = safe
                runtime.updated_at = datetime.now(UTC)
                metadata = {
                    "runtime_state": safe["state"],
                    "workload_count": safe["container_count"],
                    "cleanup_status": safe["cleanup"],
                    "execution_mode": "isolated_docker",
                    "cpu_percent": sum(w["cpu_percent"] for w in safe["workloads"])
                    if safe["workloads"]
                    and all(w["cpu_percent"] is not None for w in safe["workloads"])
                    else None,
                    "memory_bytes": sum(w["memory_bytes"] for w in safe["workloads"])
                    if safe["workloads"]
                    and all(w["memory_bytes"] is not None for w in safe["workloads"])
                    else None,
                }
                emit(
                    db,
                    evaluation,
                    "RUNTIME_TEARDOWN"
                    if safe["state"] in {"TEARDOWN", "CLEANED", "CLEANUP_FAILED"}
                    else "RUNTIME_UPDATED",
                    source="PROVISIONER",
                    destination="API",
                    metadata=metadata,
                )
                isolation_state = (safe.get("isolation") or {}).get("enforcement")
                if isolation_state == "FAILED" and last_isolation[0] != "FAILED":
                    emit(
                        db,
                        evaluation,
                        "CPU_ALLOCATION_FAILED",
                        source="PROVISIONER",
                        metadata={
                            "security_profile": "REDUCED_INTERFERENCE",
                            "affinity_status": "FAILED",
                            "reason_code": "EFFECTIVE_CPU_AFFINITY_FAILED",
                        },
                    )
                if isolation_state == "VERIFIED" and last_isolation[0] != "VERIFIED":
                    emit(
                        db,
                        evaluation,
                        "CPU_AFFINITY_VERIFIED",
                        source="PROVISIONER",
                        metadata={
                            "security_profile": safe["isolation"]["security_profile"],
                            "affinity_status": "VERIFIED",
                            "allocation_digest": safe["isolation"]["allocation_digest"],
                        },
                    )
                last_isolation[0] = isolation_state
                for probe in safe["probes"][previous[0] :]:
                    emit(
                        db,
                        evaluation,
                        "SECURITY_PROBE_RESULT",
                        source="PROVISIONER",
                        destination="API",
                        metadata={
                            "probe_id": probe["probe_id"],
                            "probe_status": probe["status"],
                            "execution_mode": "isolated_docker",
                        },
                    )
                previous[0] = len(safe["probes"])
                db.commit()

        return record

    def operation(self, request):
        with Session(self.engine) as db:
            actor = db.get(User, request.actor_id)
            if actor is None or not actor.is_active:
                raise AccessError(403, "forbidden", "Not permitted")
            if request.operation == "capabilities":
                profile = self.docker.profile()
                available = profile["available"]
                for image in self.images.values():
                    available = (
                        available
                        and self.docker.json("image", "inspect", image)[0]["Id"]
                        == image
                    )
                local = model_manifest("local")
                model_option = {
                    "provider": "local",
                    "model_id": local.model_id,
                    "revision": local.revision,
                    "artifact_sha256": local.artifact_sha256,
                    "resource_profile": local.resource_profile,
                    "available": False,
                    "reason": "Run trusted model preparation and image build",
                    "image_digest": None,
                }
                try:
                    runtime = local_runtime()
                    if (
                        available
                        and self.docker.json("image", "inspect", runtime["image"])[0][
                            "Id"
                        ]
                        == runtime["image"]
                    ):
                        model_option.update(
                            available=True,
                            reason="Pinned local CPU model prepared; actual readiness checked on launch",
                            image_digest=runtime["image"],
                        )
                except (OSError, ValueError, KeyError, TypeError, EngineError):
                    pass
                reduced_available = False
                try:
                    reduced_available = available and bool(discover().pool())
                except ValueError:
                    pass
                return {
                    "reduced_interference_available": reduced_available,
                    "runtime_owner": self.owner,
                    "images": self.images,
                    "available": available,
                    "reason": "Fixed confined Docker profile available"
                    if available
                    else "Required host controls unavailable",
                    "profile": profile["profile"],
                    "cgroups": profile["cgroups"],
                    "seccomp": profile["seccomp"],
                    "block_io": "UNSUPPORTED",
                    "models": [model_option],
                }
            evaluation = locked(db, request.evaluation_id)
            if (
                evaluation is None
                or actor.role != "RED_OPERATOR"
                or evaluation.owner_id != actor.id
            ):
                raise AccessError(403, "forbidden", "Not permitted")
            if (
                evaluation.execution_mode != "isolated_docker"
                or not evaluation.sealed_at
                or not evaluation.blue_approved
            ):
                raise AccessError(
                    409, "invalid_scope", "Sealed isolated evaluation required"
                )
            if request.operation != "destroy":
                contents = verify_evaluation(db, evaluation)
                expected_images = approved_images(
                    self.images, contents[2], verify_artifact=True
                )
                if evaluation.manifest.get("runtime_images") != expected_images:
                    raise AccessError(
                        409,
                        "image_digest_mismatch",
                        "Committed runtime images no longer match the trusted allowlist",
                    )
            if request.operation == "run" and (
                evaluation.status != "PROVISIONING" or evaluation.worker_claimed
            ):
                raise AccessError(
                    409, "invalid_transition", "Start already claimed or invalid state"
                )
            if request.operation == "probes" and evaluation.status not in {
                "SEALED",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
            }:
                raise AccessError(
                    409,
                    "invalid_transition",
                    "Probe run requires inactive sealed evaluation",
                )
            if request.operation == "destroy" and evaluation.status not in {
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "DESTROYED",
            }:
                raise AccessError(
                    409, "invalid_transition", "Teardown requires terminal execution"
                )
            with self.mutex:
                if (
                    self.stopping.is_set()
                    or request.evaluation_id in self.active
                    or len(self.active)
                    >= (
                        4
                        if (evaluation.manifest or {}).get("security_profile")
                        == "REDUCED_INTERFERENCE"
                        else 2
                    )
                ):
                    raise AccessError(409, "runtime_busy", "Runtime capacity busy")
                self.active.add(request.evaluation_id)
            claim = None
            try:
                claim = ExecutionClaim(
                    self.engine, evaluation.id, self.owner, self.lock_dir
                ).__enter__()
                if not claim.acquired:
                    raise AccessError(
                        409,
                        "runtime_busy",
                        "Evaluation already has an execution or recovery owner",
                    )
                job = db.get(EvaluationJob, evaluation.id)
                if (
                    request.operation == "run"
                    and job
                    and job.runtime_owner not in {None, self.owner}
                ):
                    raise AccessError(
                        409,
                        "runtime_owner_mismatch",
                        "Runtime owner does not match start intent",
                    )
                job = job or intent(db, evaluation, self.owner, request.operation)
                if request.operation != "run":
                    job = intent(db, evaluation, self.owner, request.operation)
                job.runtime_owner, job.state, job.claim_id = (
                    self.owner,
                    "RUNNING",
                    claim.claim_id,
                )
                job.updated_at = datetime.now(UTC)
                if request.operation == "destroy":
                    db.commit()
                    if not self.finish_job(evaluation.id, claim):
                        raise AccessError(
                            503, "cleanup_failed", "Cleanup was not verified"
                        )
                    evaluation = locked(db, evaluation.id)
                    if evaluation.status != "DESTROYED":
                        transition(db, evaluation, "DESTROYED")
                    db.commit()
                    claim.close()
                    with self.mutex:
                        self.active.remove(request.evaluation_id)
                    return {"accepted": True}
                eid = evaluation.id
                budget = (
                    CampaignBudget if "campaign" in evaluation.manifest else Budget
                ).model_validate(evaluation.manifest["budget"])
                db.commit()
                threading.Thread(
                    target=self.job,
                    args=(request.operation, eid, contents, budget, claim),
                    daemon=True,
                ).start()
                return {"accepted": True}
            except Exception:
                if claim:
                    claim.close()
                with self.mutex:
                    self.active.discard(request.evaluation_id)
                raise

    def job(self, operation, eid, contents, budget, claim=None):
        claim = (
            claim
            or ExecutionClaim(self.engine, eid, self.owner, self.lock_dir).__enter__()
        )
        if not claim.acquired:
            return
        adapter = None
        reason = None
        old_affinity = None
        try:
            with Session(self.engine) as db:
                evaluation = locked(db, eid)
                job = db.get(EvaluationJob, eid) or intent(
                    db, evaluation, self.owner, operation
                )
                if operation == "run" and (
                    evaluation.status != "PROVISIONING" or evaluation.worker_claimed
                ):
                    return
                job.state, job.runtime_owner, job.claim_id = (
                    "RUNNING",
                    self.owner,
                    claim.claim_id,
                )
                db.commit()
                contents = verify_evaluation(db, evaluation)
                campaign = evaluation.manifest.get("campaign")
                images = approved_images(self.images, contents[2], verify_artifact=True)
                profile = evaluation.manifest.get("security_profile", "STANDARD")
                emit(
                    db,
                    evaluation,
                    "CPU_RESERVATION_REQUESTED",
                    source="PROVISIONER",
                    metadata={
                        "security_profile": profile,
                        "affinity_status": "PENDING",
                    },
                )
                db.commit()

            def waiting_check():
                claim.check()
                with Session(self.engine) as waiting_db:
                    current = locked(waiting_db, eid)
                    if current.status not in {
                        "PROVISIONING",
                        "SEALED",
                        "COMPLETED",
                        "FAILED",
                        "CANCELLED",
                    } or (operation == "run" and current.status != "PROVISIONING"):
                        raise EngineError("CPU_WAIT_CANCELLED")

            self.allocations.engine = self.docker
            waiting_started = time.monotonic()
            allocation = self.allocations.wait(
                self.owner, eid, claim.claim_id, profile, waiting_check
            )
            queue_wait_ms = int((time.monotonic() - waiting_started) * 1000)
            if allocation["cpus"]:
                old_affinity = os.sched_getaffinity(0)
                os.sched_setaffinity(0, allocation["cpus"])
                if os.sched_getaffinity(0) != set(allocation["cpus"]):
                    raise EngineError("COORDINATOR_AFFINITY_FAILED")
            with Session(self.engine) as allocation_db:
                current = locked(allocation_db, eid)
                emit(
                    allocation_db,
                    current,
                    "CPU_ALLOCATION_GRANTED",
                    source="PROVISIONER",
                    metadata={
                        "security_profile": profile,
                        "allocation_digest": hashlib.sha256(
                            canonical(allocation)
                        ).hexdigest(),
                        "queue_wait_ms": queue_wait_ms,
                    },
                )
                allocation_db.commit()
            factory = partial(
                DockerRuntimeAdapter,
                owner=self.owner,
                evaluation_id=eid,
                images=images,
                report=self.report(eid, claim),
                engine=DockerEngine(guard=claim.check),
                campaign=campaign,
                allocation=allocation,
                queue_wait_ms=queue_wait_ms,
                scope_claim=partial(
                    ExecutionClaim,
                    self.engine,
                    owner=self.owner,
                    lock_dir=self.lock_dir,
                ),
            )
            if operation == "run":
                run_evaluation(self.engine, eid, adapter_factory=factory, claim=claim)
            else:
                adapter = factory(contents, budget)
                adapter.prepare()
                adapter.probes()
        except Exception as error:  # noqa: BLE001 - sanitized trusted job failure
            print(
                json.dumps(
                    {
                        "event": "runtime_job_failed",
                        "exception_type": type(error).__name__,
                    }
                ),
                flush=True,
            )
            reason = (
                "CPU_CAPACITY_UNAVAILABLE"
                if isinstance(error, CapacityError)
                else "RUNTIME_OPERATION_FAILED"
            )
            try:
                with Session(self.engine) as failed_db:
                    current = locked(failed_db, eid)
                    if current.manifest:
                        emit(
                            failed_db,
                            current,
                            "CPU_ALLOCATION_FAILED",
                            source="PROVISIONER",
                            metadata={
                                "security_profile": current.manifest.get(
                                    "security_profile", "STANDARD"
                                ),
                                "affinity_status": "FAILED",
                                "reason_code": reason,
                            },
                        )
                    failed_db.commit()
            except Exception:  # noqa: BLE001 - sanitized failure telemetry may be unavailable
                print(
                    "CPU failure telemetry unavailable; recovery remains pending",
                    flush=True,
                )
        finally:
            if adapter:
                try:
                    adapter.close()
                except Exception:  # noqa: BLE001 - recovery must retain labelled resources
                    print("Runtime cleanup requires reconciliation", flush=True)
            with self.mutex:
                self.active.discard(eid)
            try:
                self.finish_job(eid, claim, reason)
            except Exception:  # noqa: BLE001 - leave durable intent for retry
                print("Runtime recovery remains pending", flush=True)
            finally:
                claim.close()
                if old_affinity is not None:
                    os.sched_setaffinity(0, old_affinity)

    def finish_job(self, eid, claim, reason=None):
        # The host lock remains held even if the DB session failed. Cleanup must
        # not depend on telemetry/transaction availability.
        try:
            with Session(self.engine) as db:
                evaluation = locked(db, eid)
                job = db.get(EvaluationJob, eid)
                if job and job.claim_id not in {None, claim.claim_id}:
                    return False
                if evaluation:
                    if reason or evaluation.status in ACTIVE:
                        interrupted(db, evaluation, reason or "WORKER_INTERRUPTED")
                    emit(
                        db,
                        evaluation,
                        "CLEANUP_ATTEMPTED",
                        source="PROVISIONER",
                        metadata={"execution_mode": "isolated_docker"},
                    )
                    if job:
                        job.state = "RECOVERING"
                    db.commit()
        except Exception:  # noqa: BLE001 - database failure must not prevent teardown
            print("Cleanup telemetry unavailable; recovery remains pending", flush=True)
        try:
            helpers_cleaned = True
            for kind in ("container", "network"):
                args = ["ps", "-aq"] if kind == "container" else ["network", "ls", "-q"]
                ids = (
                    self.docker.command(
                        *args,
                        "--filter",
                        f"label=io.nexus.owner={self.owner}",
                        "--filter",
                        f"label=io.nexus.cpu-parent={eid}",
                    )
                    .decode()
                    .split()
                )
                for rid in ids:
                    item = self.docker.json(
                        *(
                            ["inspect", rid]
                            if kind == "container"
                            else ["network", "inspect", rid]
                        )
                    )[0]
                    labels = (
                        item["Config"]["Labels"]
                        if kind == "container"
                        else item["Labels"]
                    )
                    if labels.get("io.nexus.owner") != self.owner or labels.get(
                        "io.nexus.cpu-parent"
                    ) != str(eid):
                        helpers_cleaned = False
                        continue
                    child = str(UUID(labels["io.nexus.evaluation"]))
                    helpers_cleaned = (
                        self.docker.cleanup(self.owner, child) and helpers_cleaned
                    )
            cleaned = self.docker.cleanup(self.owner, str(eid)) and helpers_cleaned
        except (EngineError, OSError):
            cleaned = False
        try:
            revoked = self.docker.credentials_revoked(self.owner, str(eid))
        except (EngineError, OSError):
            revoked = False
        cleaned = cleaned and revoked
        self.allocations.engine = self.docker
        released = self.allocations.release(
            self.owner, eid, cleaned=cleaned, revoked=revoked
        )
        cleaned = cleaned and released
        with Session(self.engine) as db:
            evaluation = locked(db, eid)
            if evaluation is None:
                return cleaned
            job = db.get(EvaluationJob, eid) or intent(db, evaluation, self.owner)
            if job.claim_id not in {None, claim.claim_id}:
                return False
            if reason or evaluation.status in ACTIVE:
                interrupted(db, evaluation, reason or "WORKER_INTERRUPTED")
            job.claim_id, job.runtime_owner = claim.claim_id, self.owner
            job.state, job.cleanup = (
                ("FINISHED", "VERIFIED") if cleaned else ("RECOVERING", "FAILED")
            )
            job.credentials_revoked = revoked
            job.reason_code = reason or (None if cleaned else "CLEANUP_NOT_VERIFIED")
            job.updated_at = datetime.now(UTC)
            runtime = db.get(RuntimeRecord, eid)
            if runtime:
                safe = {
                    **runtime.snapshot,
                    "state": "CLEANED" if cleaned else "CLEANUP_FAILED",
                    "cleanup": job.cleanup,
                    "container_count": 0
                    if cleaned
                    else runtime.snapshot.get("container_count", 0),
                }
                safe["workloads"] = [
                    {**w, "health": "REMOVED" if cleaned else "UNKNOWN"}
                    for w in safe.get("workloads", [])
                ]
                runtime.snapshot = RuntimeSnapshot.model_validate(safe).model_dump(
                    mode="json"
                )
                runtime.updated_at = datetime.now(UTC)
                emit(
                    db,
                    evaluation,
                    "RUNTIME_TEARDOWN",
                    source="PROVISIONER",
                    metadata={
                        "runtime_state": safe["state"],
                        "cleanup_status": job.cleanup,
                        "workload_count": safe["container_count"],
                        "execution_mode": "isolated_docker",
                    },
                )
            if cleaned and evaluation.manifest:
                emit(
                    db,
                    evaluation,
                    "CPU_ALLOCATION_RELEASED",
                    source="PROVISIONER",
                    metadata={
                        "security_profile": evaluation.manifest.get(
                            "security_profile", "STANDARD"
                        ),
                        "affinity_status": "RELEASED",
                    },
                )
            if revoked:
                emit(db, evaluation, "CREDENTIALS_REVOKED", source="PROVISIONER")
            emit(
                db,
                evaluation,
                "CLEANUP_VERIFIED" if cleaned else "RECOVERY_FAILED",
                source="PROVISIONER",
                metadata={
                    "cleanup_status": job.cleanup,
                    "reason_code": None if cleaned else "CLEANUP_NOT_VERIFIED",
                },
            )
            db.commit()
        return cleaned

    def reconcile(self):
        """Skip live claims; recover only this owner's journal and labelled orphans."""
        scopes = set()
        for kind in ("container", "network"):
            for rid in self.docker.resources(kind, self.owner):
                item = self.docker.json(
                    *(
                        ["inspect", rid]
                        if kind == "container"
                        else ["network", "inspect", rid]
                    )
                )[0]
                labels = (
                    item["Config"]["Labels"] if kind == "container" else item["Labels"]
                )
                if labels.get("io.nexus.kind") not in {
                    "red",
                    "blue",
                    "model",
                    "gateway",
                    "network",
                    "witness",
                    "witness_network",
                }:
                    continue
                try:
                    scopes.add(UUID(labels.get("io.nexus.evaluation", "")))
                except ValueError:
                    continue
        with Session(self.engine) as db:
            jobs = list(
                db.scalars(
                    select(EvaluationJob.evaluation_id).where(
                        EvaluationJob.runtime_owner == self.owner,
                        (EvaluationJob.state != "FINISHED")
                        | (EvaluationJob.cleanup != "VERIFIED"),
                        # Do not take even a temporary claim during the API's
                        # bounded handoff: the control handler needs that claim
                        # to accept the start. Retain the post-claim check below
                        # for candidates discovered through resource labels.
                        ~(
                            (EvaluationJob.state == "PENDING")
                            & (
                                EvaluationJob.updated_at
                                > datetime.now(UTC) - timedelta(seconds=15)
                            )
                        ),
                    )
                )
            )
        candidates = scopes | set(jobs)
        for eid in candidates:
            with ExecutionClaim(self.engine, eid, self.owner, self.lock_dir) as claim:
                if not claim.acquired:
                    continue
                with Session(self.engine) as db:
                    evaluation = locked(db, eid)
                    job = db.get(EvaluationJob, eid)
                    if job and job.runtime_owner not in {None, self.owner}:
                        continue
                    if evaluation and evaluation.status in ACTIVE and job is None:
                        # Legacy running software has no ownership claim. Never infer
                        # its death from a rolling schema upgrade alone.
                        continue
                    if (
                        evaluation
                        and evaluation.status in ACTIVE
                        and job
                        and job.runtime_owner is None
                        and evaluation.worker_claimed
                    ):
                        # A mixed-version legacy worker cannot prove ownership using
                        # the new claim protocol. Preserve it for maintenance review.
                        continue
                    if (
                        job
                        and job.state == "PENDING"
                        and job.updated_at > datetime.now(UTC) - timedelta(seconds=15)
                    ):
                        continue
                    if evaluation:
                        job = job or intent(db, evaluation, self.owner, "destroy")
                        job.state, job.claim_id = "RECOVERING", claim.claim_id
                        emit(
                            db,
                            evaluation,
                            "RECOVERY_STARTED",
                            source="PROVISIONER",
                            metadata={"execution_mode": "isolated_docker"},
                        )
                        emit(
                            db,
                            evaluation,
                            "RUNTIME_FOUND" if eid in scopes else "RUNTIME_MISSING",
                            source="PROVISIONER",
                        )
                        interrupted(db, evaluation)
                        db.commit()
                cleaned = self.finish_job(
                    eid,
                    claim,
                    "PROCESS_INTERRUPTED" if eid in jobs else "ORPHAN_RECONCILED",
                )
                if evaluation:
                    with Session(self.engine) as db:
                        evaluation = locked(db, eid)
                        emit(
                            db,
                            evaluation,
                            "EVALUATION_RECONCILED",
                            source="PROVISIONER",
                            metadata={
                                "status": evaluation.status,
                                "cleanup_status": "VERIFIED" if cleaned else "FAILED",
                            },
                        )
                        db.commit()

    def recovery_loop(self):
        while not self.stopping.wait(2):
            try:
                self.reconcile()
            except Exception:  # noqa: BLE001 - periodic fail-closed retry
                print("Recovery dependency unavailable; retry pending", flush=True)


def main():
    STATE.mkdir(exist_ok=True, mode=0o700)
    singleton = (STATE / "provisioner.lock").open("a")
    try:
        fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("PROVISIONER_ALREADY_RUNNING") from None
    control_dir = STATE / "control"
    control_dir.mkdir(mode=0o755, exist_ok=True)
    os.chmod(control_dir, 0o755)
    owner_file = STATE / "owner"
    if not owner_file.exists():
        owner_file.write_text(str(uuid4()))
    owner = str(UUID(owner_file.read_text().strip()))
    key_file = STATE / "control.key"
    if not key_file.exists():
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_hex(32))
    key = bytes.fromhex(key_file.read_text().strip())
    images = {
        role: image_id(value)
        for role, value in json.loads((STATE / "images.json").read_text()).items()
    }
    if set(images) != {"red", "blue", "model", "gateway"}:
        raise SystemExit("IMAGE_ALLOWLIST_INVALID")

    class ProvisionerSettings(BaseSettings):
        model_config = SettingsConfigDict(
            env_prefix="NEXUS_", extra="ignore", hide_input_in_errors=True
        )
        provisioner_database_url: SecretStr

    trusted = ProvisionerSettings(_env_file=CONFIG_FILE)
    settings = Settings(
        _env_file=CONFIG_FILE,
        database_url=trusted.provisioner_database_url,
    )
    configure_logging(settings.log_level)
    engine = make_engine(settings)
    try:
        with engine.connect() as connection:
            validate_runtime(connection)
            if (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                != SCHEMA_REVISION
            ):
                raise ValueError("MIGRATION_REQUIRED")
    except Exception:  # noqa: BLE001 - suppress connection credentials
        raise SystemExit("PROVISIONER_DATABASE_VALIDATION_FAILED") from None
    service = Provisioner(engine, owner, images)
    service.reconcile()
    path = control_dir / "provisioner.sock"
    if path.exists():
        with socket.socket(socket.AF_UNIX) as existing:
            existing.settimeout(1)
            try:
                existing.connect(str(path))
            except (ConnectionRefusedError, FileNotFoundError):
                path.unlink(missing_ok=True)
            else:
                raise SystemExit("PROVISIONER_SOCKET_IN_USE")

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            nonce = ""
            try:
                self.connection.settimeout(5)
                _, uid, _ = struct.unpack(
                    "3i",
                    self.connection.getsockopt(
                        socket.SOL_SOCKET, socket.SO_PEERCRED, 12
                    ),
                )
                if uid != 10001:
                    raise AccessError(
                        403, "confined_profile_required", "Confined API required"
                    )
                raw = self.rfile.readline(8193)
                if len(raw) > 8192:
                    raise ValueError
                value = json.loads(raw)
                if set(value) != {"request", "signature"}:
                    raise ValueError
                request = ControlRequest.model_validate(value["request"])
                signature = hmac.new(
                    key, canonical(value["request"]), hashlib.sha256
                ).hexdigest()
                nonce = request.nonce
                if (
                    not hmac.compare_digest(signature, value["signature"])
                    or abs(time.time() - request.timestamp) > 15
                ):
                    raise ValueError
                with service.mutex:
                    service.seen = {
                        k: v for k, v in service.seen.items() if v > time.time() - 60
                    }
                    if nonce in service.seen or len(service.seen) >= 10000:
                        raise ValueError
                    service.seen[nonce] = time.time()
                result = service.operation(request)
                response = {"ok": True, "nonce": nonce, "result": result}
            except AccessError as error:
                response = {"ok": False, "nonce": nonce, "status": error.status}
            except Exception as error:  # noqa: BLE001 - never expose private control exception text
                print(
                    json.dumps(
                        {
                            "event": "runtime_control_failed",
                            "exception_type": type(error).__name__,
                        }
                    ),
                    flush=True,
                )
                response = {"ok": False, "nonce": nonce, "status": 503}
            signed = hmac.new(key, canonical(response), hashlib.sha256).hexdigest()
            try:
                self.wfile.write(
                    canonical({"response": response, "signature": signed}) + b"\n"
                )
            except OSError:
                pass

    with socketserver.ThreadingUnixStreamServer(str(path), Handler) as server:
        os.chmod(
            path, 0o666
        )  # Parent host directory is private; requests additionally require UID+HMAC.
        print(
            "Trusted provisioner ready; confined UID and signed operations required",
            flush=True,
        )
        recovery = threading.Thread(target=service.recovery_loop, daemon=True)
        recovery.start()

        def shutdown(*_):
            service.stopping.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        try:
            server.serve_forever()
        finally:
            service.stopping.set()
            recovery.join(timeout=5)
            # Bounded grace; a later process claims and cleans any remaining job.
            deadline = time.monotonic() + 30
            while service.active and time.monotonic() < deadline:
                time.sleep(0.1)


if __name__ == "__main__":
    main()
