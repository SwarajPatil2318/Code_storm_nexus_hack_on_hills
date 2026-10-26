"""Durable intent and exclusive claims. Interrupted work is never automatically replayed."""

import fcntl
import hashlib
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from nexus_api.lifecycle import emit, locked, transition
from nexus_api.models import Evaluation, EvaluationJob

ACTIVE = {"PROVISIONING", "RUNNING", "FINALIZING"}


class ClaimLost(Exception):
    pass


def intent(db, evaluation, owner=None, operation="run"):
    job = db.get(EvaluationJob, evaluation.id)
    if job is None:
        job = EvaluationJob(evaluation_id=evaluation.id)
        db.add(job)
    job.runtime_owner, job.operation = owner, operation
    job.state, job.cleanup, job.credentials_revoked = "PENDING", "PENDING", False
    job.claim_id, job.reason_code = None, None
    job.updated_at = datetime.now(UTC)
    db.flush()
    return job


class ExecutionClaim:
    """DB session lock plus same-host exclusion across DB outages for Docker effects.

    The runtime owner must use one shared private lock directory on one host. No lease
    expiry can evict a live process; a hung process requires supervised termination.
    """

    def __init__(self, engine, eid, owner=None, lock_dir=None):
        self.engine, self.eid, self.owner = engine, eid, owner
        self.lock_dir = Path(lock_dir) if lock_dir else None
        self.connection, self.file = None, None
        self.key, self.claim_id = None, uuid4()
        self.acquired = False
        self.mutex = threading.Lock()

    def __enter__(self):
        try:
            self.connection = self.engine.connect()
            scope = self.connection.execute(
                text("SELECT current_database(), current_schema()")
            ).one()
            name = f"nexus-job:{scope[0]}:{scope[1]}:{self.eid}"
            self.key = int.from_bytes(
                hashlib.sha256(name.encode()).digest()[:8], "big", signed=True
            )
            if self.lock_dir:
                self.lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                from nexus_api.proof_identity import publish_claim_reader

                directory_fd = os.open(self.lock_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    publish_claim_reader(directory_fd)
                finally:
                    os.close(directory_fd)
                path = self.lock_dir / f"{self.owner}-{self.eid}.lock"
                fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                directory_fd = os.open(self.lock_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    publish_claim_reader(directory_fd, fd)
                except Exception:
                    os.close(fd)
                    raise
                finally:
                    os.close(directory_fd)
                self.file = os.fdopen(fd, "w")
                try:
                    fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    self.close()
                    return self
            self.acquired = bool(
                self.connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key})
            )
            self.connection.commit()
            if not self.acquired:
                self.close()
            return self
        except Exception:
            self.close()
            raise

    def check(self):
        with self.mutex:
            if not self.acquired or self.connection is None or self.connection.invalidated:
                raise ClaimLost("EXECUTION_CLAIM_LOST")
            # Never reconnect a lost session and silently assume the old lock survived.
            try:
                self.connection.execute(text("SELECT 1"))
                self.connection.commit()
            except Exception:
                self.acquired = False
                raise ClaimLost("EXECUTION_CLAIM_LOST") from None

    def close(self):
        if self.connection is not None:
            try:
                if self.acquired and not self.connection.invalidated:
                    self.connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": self.key}
                    )
                    self.connection.commit()
            except Exception:
                self.connection.invalidate()
            finally:
                # An invalidated connection must not be reused to establish a new lock.
                self.connection.close()
                self.connection = None
        if self.file:
            self.file.close()
            self.file = None
        self.acquired = False

    def __exit__(self, *_):
        self.close()


def interrupted(db, evaluation, reason="PROCESS_INTERRUPTED"):
    if evaluation.status in ACTIVE:
        transition(db, evaluation, "FAILED")
        emit(
            db,
            evaluation,
            "EVALUATION_INTERRUPTED",
            source="PROVISIONER" if evaluation.execution_mode == "isolated_docker" else "API",
            metadata={"reason_code": reason, "execution_mode": evaluation.execution_mode},
        )


def recover_local(engine):
    """Only abandoned local jobs; isolated work belongs to the separate provisioner."""
    if engine is None:
        return
    with Session(engine) as db:
        candidates = list(
            db.scalars(
                select(Evaluation.id).where(
                    Evaluation.execution_mode == "local_mock", Evaluation.status.in_(ACTIVE)
                )
            )
        )
    for eid in candidates:
        with ExecutionClaim(engine, eid) as claim:
            if not claim.acquired:
                continue
            with Session(engine) as db:
                evaluation = locked(db, eid)
                job = db.get(EvaluationJob, eid)
                # Allow a bounded handoff interval between the commit and BackgroundTasks.
                if (
                    job
                    and job.state == "PENDING"
                    and job.updated_at > datetime.now(UTC) - timedelta(seconds=15)
                ):
                    continue
                emit(db, evaluation, "RECOVERY_STARTED", metadata={"execution_mode": "local_mock"})
                interrupted(db, evaluation)
                job = job or intent(db, evaluation)
                job.state, job.cleanup, job.credentials_revoked = "FINISHED", "VERIFIED", True
                job.reason_code, job.updated_at = "PROCESS_INTERRUPTED", datetime.now(UTC)
                emit(
                    db,
                    evaluation,
                    "EVALUATION_RECONCILED",
                    metadata={"status": evaluation.status, "execution_mode": "local_mock"},
                )
                db.commit()
