"""Bounded real/MOCK campaigns using the established monitor and verified runtime boundary."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api.campaign_adapter import CampaignMockAdapter
from nexus_api.campaign_results import InferenceResult
from nexus_api.campaign_schemas import AttackCorpus, CampaignBudget, ModelManifest
from nexus_api.evaluation_rules import conversation, parse_conversation, score
from nexus_api.lifecycle import emit, locked, transition, verify_evaluation
from nexus_api.models import CaseRecord, Evaluation, EvaluationResult
from nexus_api.monitor import MediationDenied, ReferenceMonitor
from nexus_api.runtime_schemas import Envelope
from nexus_api.versioning import FLOWS, canonical


class CampaignInterrupted(Exception):
    pass


class IsolationEnforcementFailed(Exception):
    pass


def run_campaign(engine, evaluation_id, adapter_factory, *, check_ownership=lambda: None):
    adapter, cleaned, failed, model_stopped = None, False, None, False
    stop = threading.Event()
    deadline = [float("inf")]
    provider = ["mock"]

    def check_cancel():
        check_ownership()
        if stop.is_set():
            raise CampaignInterrupted("CAMPAIGN_STOPPED")
        with Session(engine) as db:
            evaluation = db.get(Evaluation, evaluation_id)
            if evaluation.status not in {"PROVISIONING", "RUNNING", "FINALIZING"}:
                raise CampaignInterrupted("EVALUATION_CANCELLED")
        if time.monotonic() > deadline[0]:
            raise CampaignInterrupted("TOTAL_DEADLINE_EXCEEDED")

    def event(kind, metadata=None, correlation=None, *, terminal=False):
        with Session(engine) as db:
            evaluation = locked(db, evaluation_id)
            if not terminal and evaluation.status not in {"PROVISIONING", "RUNNING", "FINALIZING"}:
                raise CampaignInterrupted("EVALUATION_CANCELLED")
            emit(
                db,
                evaluation,
                kind,
                source="MODEL_WORKER" if kind.startswith("MODEL_") else "REFERENCE_MONITOR",
                correlation=correlation,
                metadata={"provider": provider[0], **(metadata or {})},
            )
            db.commit()

    try:
        with Session(engine, expire_on_commit=False) as db:
            evaluation = locked(db, evaluation_id)
            if evaluation.status != "PROVISIONING" or evaluation.worker_claimed:
                return
            evaluation.worker_claimed = True
            contents = verify_evaluation(db, evaluation)
            corpus = AttackCorpus.model_validate(contents[0])
            budget = CampaignBudget.model_validate(evaluation.manifest["budget"])
            model = ModelManifest.model_validate(contents[2])
            provider[0] = model.provider
            deadline[0] = time.monotonic() + budget.timeout_seconds
            mode, campaign = evaluation.execution_mode, evaluation.manifest["campaign"]
            policy_digest = evaluation.manifest["versions"][3]["sha256"]
            db.commit()
        factory = CampaignMockAdapter if mode == "local_mock" else adapter_factory
        adapter = factory(
            contents,
            budget,
            campaign=campaign,
            check_cancel=check_cancel,
            on_model_event=lambda kind, data: event(kind, data),
        )
        if adapter.isolated != (mode == "isolated_docker") or (
            provider[0] == "local" and not adapter.isolated
        ):
            raise ValueError("RUNTIME_PROVIDER_MISMATCH")
        adapter.prepare()
        if adapter.isolated:
            probes = adapter.probes()
            if any(p["status"] != "PASS" for p in probes if p["probe_id"] != "BLOCK_IO"):
                raise ValueError("SECURITY_PROBE_FAILED")
        check_cancel()
        with Session(engine) as db:
            evaluation = locked(db, evaluation_id)
            if evaluation.status != "PROVISIONING":
                raise CampaignInterrupted("EVALUATION_CANCELLED")
            transition(db, evaluation, "RUNNING")
            db.commit()
        monitor = ReferenceMonitor(engine, evaluation_id, policy_digest, budget)
        selected = corpus.cases[: budget.max_cases]

        def run_case(index, committed_case):
            correlation = uuid4()
            started = time.monotonic()
            case_deadline = min(deadline[0], started + budget.case_timeout_ms / 1000)
            data = {
                "case_id": committed_case.case_id,
                "case_index": index,
                "correlation_id": str(correlation),
                "policy_decision": None,
                "input_action": None,
                "output_action": None,
                "model_execution": "SKIPPED",
                "attack_outcome": "NOT_EVALUATED",
                "duration_ms": 0,
                "inference_ms": None,
                "prompt_tokens": None,
                "completion_tokens": None,
                "finish_reason": None,
                "error_code": None,
                "title": committed_case.title,
                "attack_category": committed_case.attack_category,
                "difficulty": committed_case.difficulty,
                "attack_input": committed_case.attack_input,
                "released_output": None,
                "criterion": committed_case.scoring.model_dump(),
                "scoring_explanation": None,
            }
            internal, finish_reason, full_roundtrip, interrupted = {}, "stop", False, None

            def case_check():
                check_cancel()
                if time.monotonic() > case_deadline:
                    raise TimeoutError("CASE_TIMEOUT")

            def mediate(index, payload):
                case_check()
                source, destination, message_type = FLOWS[index]
                envelope = Envelope(
                    message_id=uuid4(),
                    evaluation_id=evaluation_id,
                    correlation_id=correlation,
                    source_domain=source,
                    destination_domain=destination,
                    message_type=message_type,
                    timestamp=datetime.now(UTC),
                    payload=payload,
                    metadata={"adapter_version": "campaign-v1"},
                )
                try:
                    result = monitor.mediate(monitor.capability(source), envelope)
                    data["policy_decision"] = "ALLOW"
                    return result
                except MediationDenied:
                    data["policy_decision"] = "DENY"
                    raise

            try:
                case_check()
                event("ATTACK_CASE_STARTED", {"case_index": index}, correlation)
                case = adapter.campaign_case(index, correlation)
                if case != committed_case:
                    raise ValueError("COMMITTED_CORPUS_MISMATCH")
                text = canonical(conversation(case.model_dump())).decode()
                mediate(0, {"kind": "text", "text": text})
                mediate(1, {"kind": "text", "text": text})
                guarded = adapter.campaign_guard("input", text)
                data["input_action"], internal["input_reason"] = (
                    guarded["action"],
                    guarded["reason"],
                )
                event(
                    "INPUT_GUARD_EVALUATED",
                    {"case_index": index, "defence_action": guarded["action"]},
                    correlation,
                )
                mediate(
                    2, {"kind": "guard", "approved": guarded["approved"], "text": guarded["text"]}
                )
                if guarded["approved"]:
                    approved = parse_conversation(guarded["text"])
                    if approved["messages"][0] != conversation(case.model_dump())["messages"][0]:
                        raise ValueError("TRUSTED_CONTEXT_MODIFIED")
                    mediate(3, {"kind": "text", "text": guarded["text"]})
                    data["model_execution"] = "ERROR"
                    event("MODEL_INFERENCE_STARTED", {"case_index": index}, correlation)
                    result = InferenceResult.model_validate(
                        adapter.campaign_inference(
                            approved["messages"],
                            correlation,
                            timeout_ms=min(
                                budget.model_timeout_ms,
                                max(20, int((case_deadline - time.monotonic()) * 1000)),
                            ),
                        )
                    )
                    data.update(
                        model_execution="EXECUTED",
                        inference_ms=result.duration_ms,
                        prompt_tokens=result.prompt_tokens,
                        completion_tokens=result.completion_tokens,
                    )
                    finish_reason = result.finish_reason
                    data["finish_reason"] = finish_reason
                    mediate(4, {"kind": "text", "text": result.text})
                    event(
                        "MODEL_INFERENCE_COMPLETED",
                        {
                            "case_index": index,
                            "duration_ms": result.duration_ms,
                            "prompt_tokens": result.prompt_tokens,
                            "completion_tokens": result.completion_tokens,
                        },
                        correlation,
                    )
                    mediate(5, {"kind": "text", "text": result.text})
                    output = adapter.campaign_guard("output", result.text)
                    data["output_action"], internal["output_reason"] = (
                        output["action"],
                        output["reason"],
                    )
                    event(
                        "OUTPUT_GUARD_EVALUATED",
                        {"case_index": index, "defence_action": output["action"]},
                        correlation,
                    )
                    mediate(
                        6, {"kind": "guard", "approved": output["approved"], "text": output["text"]}
                    )
                    release = {
                        "kind": "campaign_release",
                        "outcome": "released" if output["approved"] else "withheld",
                        "response": output["text"] if output["approved"] else "Response withheld.",
                    }
                    full_roundtrip = True
                else:
                    release = {
                        "kind": "campaign_release",
                        "outcome": "withheld",
                        "response": "Response withheld.",
                    }
                authorized = mediate(7, release)
                adapter.deliver(authorized.payload)
                event("RESULT_RELEASED", {"case_index": index}, correlation)
                data["released_output"] = release["response"]
            except CampaignInterrupted as error:
                interrupted = error
                data["error_code"] = (
                    "TOTAL_DEADLINE_EXCEEDED"
                    if str(error) == "TOTAL_DEADLINE_EXCEEDED"
                    else "EVALUATION_CANCELLED"
                )
            except TimeoutError:
                if data["model_execution"] == "ERROR":
                    data["model_execution"] = "TIMEOUT"
                data["error_code"] = (
                    "MODEL_TIMEOUT" if data["model_execution"] == "TIMEOUT" else "CASE_TIMEOUT"
                )
            except Exception:
                data["error_code"] = (
                    "POLICY_DENIED" if data["policy_decision"] == "DENY" else "CASE_EXECUTION_ERROR"
                )
            isolation_failed = (
                getattr(adapter, "snapshot", {}).get("isolation", {}).get("enforcement") == "FAILED"
            )
            if isolation_failed:
                data["error_code"] = "ISOLATION_ENFORCEMENT_FAILED"
                stop.set()
            if data["error_code"]:
                data["released_output"] = None
                data["attack_outcome"], data["scoring_explanation"] = (
                    "NOT_EVALUATED",
                    "Execution did not produce an authorized completed observation.",
                )
            else:
                data["attack_outcome"], data["scoring_explanation"] = score(
                    case.scoring.model_dump(),
                    data["released_output"],
                    data["model_execution"],
                    blocked=data["input_action"] == "BLOCK" or data["output_action"] == "BLOCK",
                    finish_reason=finish_reason,
                    scoring_version=campaign["scoring_version"],
                )
            data["duration_ms"] = int((time.monotonic() - started) * 1000)
            with Session(engine) as db:
                evaluation = locked(db, evaluation_id)
                # A result already authorized before cancellation may finish its bounded call.
                # Do not expose a fresh successful observation after cancellation.
                if evaluation.status != "RUNNING":
                    data.update(
                        released_output=None,
                        attack_outcome="NOT_EVALUATED",
                        error_code="EVALUATION_CANCELLED",
                    )
                db.add(
                    CaseRecord(
                        evaluation_id=evaluation_id,
                        case_id=case.case_id if "case" in locals() else committed_case.case_id,
                        case_index=index,
                        correlation_id=correlation,
                        result=data,
                        private_guard=internal,
                    )
                )
                db.flush()
                emit(
                    db,
                    evaluation,
                    "ATTACK_CASE_FAILED" if data["error_code"] else "ATTACK_CASE_SCORED",
                    source="REFERENCE_MONITOR",
                    correlation=correlation,
                    metadata={
                        "provider": provider[0],
                        "case_index": index,
                        "attack_outcome": data["attack_outcome"],
                        "model_execution": data["model_execution"],
                        "duration_ms": data["duration_ms"],
                        "reason_code": data["error_code"],
                    },
                )
                count = db.scalar(
                    select(func.count())
                    .select_from(CaseRecord)
                    .where(CaseRecord.evaluation_id == evaluation_id)
                )
                emit(
                    db,
                    evaluation,
                    "EVALUATION_PROGRESS",
                    source="REFERENCE_MONITOR",
                    metadata={
                        "completed_cases": count,
                        "total_cases": len(selected),
                        "provider": provider[0],
                    },
                )
                db.commit()
            if interrupted:
                raise interrupted
            if isolation_failed:
                raise IsolationEnforcementFailed()
            return full_roundtrip and not data["error_code"]

        full_count = 0
        with ThreadPoolExecutor(max_workers=budget.concurrency) as executor:
            futures = [executor.submit(run_case, i, c) for i, c in enumerate(selected)]
            try:
                for future in as_completed(futures):
                    full_count += bool(future.result())
            except Exception:
                stop.set()
                for future in futures:
                    future.cancel()
                raise
        check_cancel()
        with Session(engine) as db:
            evaluation = locked(db, evaluation_id)
            transition(db, evaluation, "FINALIZING")
            db.commit()
        if adapter.isolated:
            adapter.probe_result(
                "MEDIATED_FLOW",
                "red",
                "broker→blue→model→blue→red",
                "PIPELINE",
                "PASS" if full_count else "INCONCLUSIVE",
                f"full_mediated_roundtrips={full_count}; provider={provider[0]}",
                "AUTHORIZED",
            )
        cleaned = adapter.close()
        if not cleaned:
            raise ValueError("CLEANUP_NOT_VERIFIED")
        event("MODEL_WORKER_STOPPED", terminal=True)
        model_stopped = True
        with Session(engine) as db:
            evaluation = locked(db, evaluation_id)
            if evaluation.status != "FINALIZING":
                return
            rows = list(
                db.scalars(select(CaseRecord).where(CaseRecord.evaluation_id == evaluation_id))
            )
            if rows and all(row.result["error_code"] for row in rows):
                transition(db, evaluation, "FAILED")
                emit(
                    db,
                    evaluation,
                    "SECURITY_PROBE_FAILED",
                    metadata={"reason_code": "ALL_CASES_FAILED"},
                )
                db.commit()
                return
            db.add(
                EvaluationResult(
                    evaluation_id=evaluation_id,
                    summary={
                        "total_requests": len(rows),
                        "allowed_count": sum(r.result["released_output"] is not None for r in rows),
                        "denied_count": sum(r.result["policy_decision"] == "DENY" for r in rows),
                        "released_results": [],
                    },
                )
            )
            transition(db, evaluation, "COMPLETED")
            db.commit()
    except CampaignInterrupted as error:
        failed = (
            "TOTAL_DEADLINE_EXCEEDED"
            if str(error) == "TOTAL_DEADLINE_EXCEEDED"
            else "CAMPAIGN_INTERRUPTED"
        )
    except IsolationEnforcementFailed:
        failed = "ISOLATION_ENFORCEMENT_FAILED"
    except Exception as error:
        logging.getLogger("nexus.execution").warning(
            "campaign_execution_failed", extra={"exception_type": type(error).__name__}
        )
        failed = "CAMPAIGN_EXECUTION_FAILED"
    finally:
        stop.set()
        if adapter and not cleaned:
            try:
                cleaned = adapter.close()
            except Exception:
                failed = "CLEANUP_OR_TELEMETRY_FAILED"
        if cleaned and not model_stopped:
            event("MODEL_WORKER_STOPPED", terminal=True)
        if failed:
            with Session(engine) as db:
                evaluation = locked(db, evaluation_id)
                if evaluation and evaluation.status in {"PROVISIONING", "RUNNING", "FINALIZING"}:
                    transition(db, evaluation, "FAILED")
                    emit(db, evaluation, "SECURITY_PROBE_FAILED", metadata={"reason_code": failed})
                    db.commit()
