"""One mediated execution engine; runtime-specific work is delegated through a fixed adapter."""

import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from nexus_api.lifecycle import emit, locked, transition, verify_evaluation
from nexus_api.models import Evaluation, EvaluationResult
from nexus_api.monitor import MediationDenied, ReferenceMonitor
from nexus_api.runtime_adapter import InProcessRuntimeAdapter
from nexus_api.runtime_schemas import Budget, Corpus, Domain, Envelope
from nexus_api.versioning import FLOWS


def runtime_event(
    engine, evaluation_id, event_type, source, destination, correlation, metadata=None
):
    with Session(engine) as db:
        evaluation = locked(db, evaluation_id)
        if evaluation.status != "RUNNING":
            raise MediationDenied("Message denied")
        emit(
            db,
            evaluation,
            event_type,
            source=source,
            destination=destination,
            correlation=correlation,
            metadata=metadata,
        )
        db.commit()


def run_evaluation(engine, evaluation_id, adapter_factory=InProcessRuntimeAdapter, *, claim=None):
    if claim is None:
        from nexus_api.models import EvaluationJob, RuntimeRecord
        from nexus_api.recovery import ExecutionClaim, intent

        with ExecutionClaim(engine, evaluation_id) as owned:
            if not owned.acquired:
                return
            with Session(engine) as db:
                evaluation = locked(db, evaluation_id)
                if evaluation.status != "PROVISIONING" or evaluation.worker_claimed:
                    return
                job = db.get(EvaluationJob, evaluation_id) or intent(db, evaluation)
                job.state, job.claim_id = "RUNNING", owned.claim_id
                db.commit()
            try:
                return run_evaluation(engine, evaluation_id, adapter_factory, claim=owned)
            finally:
                with Session(engine) as db:
                    job = db.get(EvaluationJob, evaluation_id)
                    job.state = "FINISHED"
                    # Local-only teardown has no credentials or physical resources.
                    evaluation = db.get(Evaluation, evaluation_id)
                    if evaluation.execution_mode == "local_mock":
                        job.cleanup, job.credentials_revoked = "VERIFIED", True
                    else:
                        runtime = db.get(RuntimeRecord, evaluation_id)
                        verified = bool(runtime and runtime.snapshot.get("cleanup") == "VERIFIED")
                        job.cleanup = "VERIFIED" if verified else "FAILED"
                        job.credentials_revoked = verified
                        job.state = "FINISHED" if verified else "RECOVERING"
                    job.updated_at = datetime.now(UTC)
                    db.commit()
    with Session(engine) as inspection:
        record = inspection.get(Evaluation, evaluation_id)
        is_campaign = bool(record and record.manifest and "campaign" in record.manifest)
    if is_campaign:
        from nexus_api.campaign_execution import run_campaign

        return run_campaign(engine, evaluation_id, adapter_factory, check_ownership=claim.check)
    adapter, cleaned, failure = None, False, None

    def check_cancel():
        claim.check()
        with Session(engine) as check:
            evaluation = check.get(Evaluation, evaluation_id)
            if evaluation.status not in {"PROVISIONING", "RUNNING", "FINALIZING"}:
                raise MediationDenied("Message denied")

    try:
        with Session(engine, expire_on_commit=False) as db:
            evaluation = locked(db, evaluation_id)
            if evaluation.status != "PROVISIONING" or evaluation.worker_claimed:
                return
            evaluation.worker_claimed = True
            contents = verify_evaluation(db, evaluation)
            corpus = Corpus.model_validate(contents[0])
            budget = Budget.model_validate(evaluation.manifest["budget"])
            policy_digest = evaluation.manifest["versions"][3]["sha256"]
            mode = evaluation.execution_mode
            db.commit()
        adapter = adapter_factory(contents, budget, check_cancel=check_cancel)
        if adapter.isolated != (mode == "isolated_docker"):
            raise ValueError("RUNTIME_ADAPTER_MISMATCH")
        adapter.prepare()
        if adapter.isolated:
            probes = adapter.probes()
            if any(p["status"] != "PASS" for p in probes if p["probe_id"] != "BLOCK_IO"):
                raise ValueError("SECURITY_PROBE_FAILED")
        with Session(engine) as db:
            evaluation = locked(db, evaluation_id)
            check_cancel()
            transition(db, evaluation, "RUNNING")
            db.commit()
        monitor = ReferenceMonitor(engine, evaluation_id, policy_digest, budget)
        releases, denied, mediated_completed = [], 0, 0
        for case_index in range(min(len(corpus.cases), budget.max_cases)):
            correlation = uuid4()
            case = adapter.red_case(case_index, correlation)
            if case.model_dump() != corpus.cases[case_index].model_dump():
                raise ValueError("COMMITTED_CORPUS_MISMATCH")
            text, input_approved, output_approved = case.prompt, True, True
            for index, (source, destination, message_type) in enumerate(FLOWS):
                if index == 0 and case.route != "mediated":
                    destination = Domain.INPUT if case.route == "direct_blue" else Domain.MODEL
                if index in {2, 6}:
                    payload = {
                        "kind": "guard",
                        "approved": input_approved if index == 2 else output_approved,
                        "text": text,
                    }
                elif index == 7:
                    payload = {
                        "kind": "release",
                        "outcome": "released" if output_approved else "withheld",
                        "response": "Mock response: request handled."
                        if output_approved
                        else "Response withheld.",
                    }
                else:
                    payload = {"kind": "text", "text": text}
                envelope = Envelope(
                    message_id=uuid4(),
                    evaluation_id=evaluation_id,
                    correlation_id=correlation,
                    source_domain=source,
                    destination_domain=destination,
                    message_type=message_type,
                    timestamp=datetime.now(UTC),
                    payload=payload,
                )
                try:
                    approved = monitor.mediate(monitor.capability(source), envelope)
                except MediationDenied:
                    if case.route != "mediated" and index == 0:
                        denied += 1
                        break
                    raise
                if index == 1:
                    input_approved, text = adapter.input_guard(text)
                    runtime_event(
                        engine,
                        evaluation_id,
                        "DEFENCE_INVOKED",
                        source,
                        destination,
                        correlation,
                        {"guard_stage": "input", "decision": "ALLOW" if input_approved else "DENY"},
                    )
                elif index == 2 and not input_approved:
                    final = Envelope(
                        message_id=uuid4(),
                        evaluation_id=evaluation_id,
                        correlation_id=correlation,
                        source_domain=Domain.MONITOR,
                        destination_domain=Domain.RED,
                        message_type=FLOWS[7][2],
                        timestamp=datetime.now(UTC),
                        payload={
                            "kind": "release",
                            "outcome": "withheld",
                            "response": "Response withheld.",
                        },
                    )
                    release = monitor.mediate(monitor.capability(Domain.MONITOR), final)
                    adapter.deliver(release.payload)
                    releases.append(release.payload.model_dump())
                    runtime_event(
                        engine,
                        evaluation_id,
                        "RESULT_RELEASED",
                        Domain.MONITOR,
                        Domain.RED,
                        correlation,
                    )
                    break
                elif index == 3:
                    runtime_event(
                        engine, evaluation_id, "MODEL_REQUESTED", source, destination, correlation
                    )
                    text = adapter.inference(text)
                elif index == 4:
                    runtime_event(
                        engine, evaluation_id, "MODEL_RESPONDED", source, destination, correlation
                    )
                elif index == 5:
                    output_approved, text = adapter.output_guard(text, input_approved)
                    runtime_event(
                        engine,
                        evaluation_id,
                        "DEFENCE_INVOKED",
                        source,
                        destination,
                        correlation,
                        {
                            "guard_stage": "output",
                            "decision": "ALLOW" if output_approved else "DENY",
                        },
                    )
                elif index == 7:
                    adapter.deliver(approved.payload)
                    releases.append(approved.payload.model_dump())
                    mediated_completed += 1
                    runtime_event(
                        engine, evaluation_id, "RESULT_RELEASED", source, destination, correlation
                    )
        with Session(engine) as db:
            evaluation = locked(db, evaluation_id)
            if evaluation.status != "RUNNING":
                return
            transition(db, evaluation, "FINALIZING")
            db.commit()
        if adapter.isolated:
            adapter.probe_result(
                "MEDIATED_FLOW",
                "red",
                "broker→blue→model→blue→red",
                "PIPELINE",
                "PASS" if mediated_completed else "INCONCLUSIVE",
                f"full_mediated_roundtrips={mediated_completed}; "
                f"released_results={len(releases)}; denied_probes={denied}",
                "AUTHORIZED",
            )
        cleaned = adapter.close()
        if not cleaned:
            raise ValueError("CLEANUP_NOT_VERIFIED")
        with Session(engine) as db:
            evaluation = locked(db, evaluation_id)
            if evaluation.status != "FINALIZING":
                return
            db.add(
                EvaluationResult(
                    evaluation_id=evaluation_id,
                    summary={
                        "total_requests": min(len(corpus.cases), budget.max_cases),
                        "allowed_count": len(releases),
                        "denied_count": denied,
                        "released_results": releases,
                    },
                )
            )
            transition(db, evaluation, "COMPLETED")
            db.commit()
    except Exception as error:
        logging.getLogger("nexus.execution").warning(
            "evaluation_execution_failed", extra={"exception_type": type(error).__name__}
        )
        failure = "EXECUTION_TIMEOUT" if isinstance(error, TimeoutError) else "EXECUTION_FAILED"
    finally:
        if adapter is not None and not cleaned:
            try:
                if not adapter.close():
                    failure = "CLEANUP_NOT_VERIFIED"
            except Exception:
                failure = "CLEANUP_NOT_VERIFIED"
        if failure:
            with Session(engine) as db:
                evaluation = locked(db, evaluation_id)
                if evaluation and evaluation.status in {"PROVISIONING", "RUNNING", "FINALIZING"}:
                    transition(db, evaluation, "FAILED")
                    emit(db, evaluation, "SECURITY_PROBE_FAILED", metadata={"reason_code": failure})
                    db.commit()


def fail_interrupted(engine):
    from nexus_api.recovery import recover_local

    recover_local(engine)
