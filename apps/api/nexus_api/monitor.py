"""Trusted local monitor implementation; no untrusted workload execution."""

from datetime import UTC, datetime
from threading import RLock
from time import monotonic
from uuid import UUID

from pydantic import ValidationError

from nexus_api.lifecycle import emit, locked
from nexus_api.runtime_schemas import Budget, Domain, Envelope, PolicyDecision
from nexus_api.versioning import FLOWS, canonical


class MediationDenied(Exception):
    """Uniform caller failure; detailed safe reason exists only in policy decisions."""


class ReferenceMonitor:
    def __init__(self, engine, evaluation_id, policy_digest, budget: Budget):
        self.engine, self.evaluation_id = engine, evaluation_id
        self.policy_digest, self.budget = policy_digest, budget
        self._identities = {d: object() for d in Domain}
        self._seen = set()
        self._progress = {}
        self._withheld = set()
        self._count = 0
        self._deadline = monotonic() + budget.timeout_seconds
        self._lock = RLock()

    def capability(self, domain: Domain):
        # Called only by the fixed trusted orchestrator. Never exposed as an API endpoint.
        return self._identities[domain]

    def mediate(self, capability, raw):
        with self._lock:
            return self._mediate(capability, raw)

    def _mediate(self, capability, raw):
        from sqlalchemy.orm import Session

        reason, envelope = "MALFORMED_ENVELOPE", None
        try:
            candidate = Envelope.model_validate(raw)
            message_size = len(canonical(candidate.model_dump(mode="json")))
            envelope = candidate
        except (ValidationError, ValueError, TypeError, UnicodeError):
            pass
        correlation = envelope.correlation_id if envelope else UUID(int=0)
        source, destination, message_type = "API", "API", "UNKNOWN"
        if envelope:
            source, destination, message_type = (
                envelope.source_domain,
                envelope.destination_domain,
                envelope.message_type,
            )
        with Session(self.engine, expire_on_commit=False) as db:
            evaluation = locked(db, self.evaluation_id)
            if evaluation is None:
                raise MediationDenied("Message denied")
            if envelope:
                flow = (source, destination, message_type)
                index = FLOWS.index(flow) if flow in FLOWS else -1
                identity = next(
                    (d for d, cap in self._identities.items() if cap is capability), None
                )
                if identity is None:
                    reason = "MISSING_SERVICE_IDENTITY"
                elif identity != source:
                    reason = "SOURCE_IDENTITY_MISMATCH"
                elif envelope.evaluation_id != self.evaluation_id:
                    reason = "EVALUATION_SCOPE_MISMATCH"
                elif evaluation.status != "RUNNING":
                    reason = "INVALID_EVALUATION_STATE"
                elif (
                    evaluation.execution_mode not in {"local_mock", "isolated_docker"}
                    or evaluation.sealed_at is None
                    or not evaluation.blue_approved
                    or not evaluation.manifest_digest
                    or (
                        (envelope.metadata.adapter_version == "campaign-v1")
                        != ("campaign" in evaluation.manifest)
                    )
                ):
                    reason = "INVALID_EXECUTION_SCOPE"
                elif evaluation.manifest["versions"][3]["sha256"] != self.policy_digest:
                    reason = "POLICY_DIGEST_MISMATCH"
                elif monotonic() > self._deadline:
                    reason = "DEADLINE_EXCEEDED"
                elif abs((datetime.now(UTC) - envelope.timestamp).total_seconds()) > 30:
                    reason = "MESSAGE_EXPIRED"
                elif message_size > self.budget.max_bytes:
                    reason = "MESSAGE_TOO_LARGE"
                elif self._count >= self.budget.max_messages:
                    reason = "MESSAGE_BUDGET_EXCEEDED"
                elif envelope.message_id in self._seen:
                    reason = "REPLAYED_MESSAGE"
                elif index < 0:
                    reason = "FLOW_NOT_ALLOWED"
                elif index == 0 and len(self._progress) >= self.budget.max_cases:
                    reason = "CASE_BUDGET_EXCEEDED"
                elif index != self._progress.get(correlation, 0):
                    reason = "CORRELATION_ORDER_MISMATCH"
                elif (
                    index == 7
                    and correlation in self._withheld
                    and envelope.payload.outcome != "withheld"
                ):
                    reason = "RELEASE_NOT_ALLOWED"
                else:
                    reason = "FLOW_ALLOWED"
            allowed = reason == "FLOW_ALLOWED"
            decision = PolicyDecision(
                evaluation_id=self.evaluation_id,
                correlation_id=correlation,
                source_domain=source,
                destination_domain=destination,
                message_type=message_type,
                decision="ALLOW" if allowed else "DENY",
                reason_code=reason,
                policy_digest=self.policy_digest,
                timestamp=datetime.now(UTC),
            )
            emit(
                db,
                evaluation,
                "POLICY_ALLOWED" if allowed else "POLICY_DENIED",
                source=source,
                destination=destination,
                correlation=correlation,
                metadata={
                    "decision": decision.decision,
                    "reason_code": reason,
                    "message_type": message_type,
                    "policy_digest": self.policy_digest,
                    "policy_version": decision.policy_version,
                },
            )
            db.commit()
        self._count += 1
        if not allowed:
            raise MediationDenied("Message denied")
        self._seen.add(envelope.message_id)
        self._progress[correlation] = index + 1
        if index in {2, 6} and not envelope.payload.approved:
            self._withheld.add(correlation)
            if index == 2:
                self._progress[correlation] = 7  # Denied input may only release a withheld result.
        return envelope
