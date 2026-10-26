"""Bounded read-only archive reader; exact local/original subject grants, no federation."""

import hashlib
import json
import os
import stat
from pathlib import Path

from pydantic import ValidationError

from nexus_api.center_schemas import ArchiveCatalog, CenterSource, CenterVersion
from nexus_api.proof_format import MAX_BUNDLE, Verification, canonical, parse, unb64, verify


def bounded(directory, name, limit):
    if Path(name).name != name or directory.is_symlink():
        raise ValueError("ARCHIVE_PATH")
    fd = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("ARCHIVE_FILE")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("ARCHIVE_LIMIT")
    return data


def catalog(settings):
    if not settings.assurance_catalog_dir:
        return None, "NOT_CONFIGURED"
    try:
        d = Path(settings.assurance_catalog_dir)
        c = ArchiveCatalog.model_validate_json(bounded(d, "catalog.json", 131072))
        if len({e.id for e in c.entries}) != len(c.entries):
            raise ValueError("DUPLICATE_ARCHIVE")
        return c, "AVAILABLE"
    except (OSError, ValueError, ValidationError):
        return None, "UNAVAILABLE"


def permitted(entry, user):
    return next(
        (g for g in entry.grants if g.local_subject == user.id and g.role == user.role), None
    )


def decimal_values(value):
    if isinstance(value, dict):
        if set(value) == {"decimal"}:
            return float(value["decimal"])
        return {k: decimal_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decimal_values(v) for v in value]
    return value


def load(entry, grant, catalog_value, settings):
    sid = str(entry.id)
    source = CenterSource(
        id=sid,
        environment=entry.environment,
        evaluation_id=entry.evaluation_id,
        snapshot_id=entry.snapshot_id,
        profile=grant.role,
        original_subject=grant.original_subject,
        bundle_sha256=entry.bundle_sha256,
        condition="MISSING",
        coverage="UNCONFIRMED",
        provenance="RECORDED_APPLICATION"
        if entry.report_kind == "runtime"
        else "OPERATOR_EXPERIMENT_ATTESTATION",
    )
    try:
        raw = bounded(Path(settings.assurance_catalog_dir), sid + ".json", MAX_BUNDLE)
    except (OSError, ValueError):
        return source, None, None
    result = verify(raw, catalog_value.trusted_keys)
    source = source.model_copy(update={"verification": result})
    if hashlib.sha256(raw).hexdigest() != entry.bundle_sha256:
        source = source.model_copy(update={"condition": "INVALID"})
        source = source.model_copy(
            update={"verification": Verification(status="INVALID", category="ARCHIVE_DIGEST")}
        )
        return source, None, None
    if result.status not in {"VALID", "UNTRUSTED_SIGNER"}:
        source = source.model_copy(
            update={"condition": "INCOMPLETE" if result.status == "INCOMPLETE" else "INVALID"}
        )
        return source, None, None
    bundle = parse(raw)
    p = bundle["receipt"]["payload"]
    if (
        p["evaluation_id"] != str(entry.evaluation_id)
        or p["snapshot_id"] != str(entry.snapshot_id)
        or p["profile"] != grant.role
        or p["subject_id"] != str(grant.original_subject)
        or p["coverage"] != "AUTHORIZED_PROJECTION_ONLY"
    ):
        source = source.model_copy(update={"condition": "INVALID"})
        source = source.model_copy(
            update={"verification": Verification(status="INVALID", category="SCOPE")}
        )
        return source, None, None
    values = [parse(unb64(f["content"])) for f in bundle["files"]]
    m, events, artifacts, results = values
    source = source.model_copy(update={"signed_at": p["signed_at"]})
    source = source.model_copy(update={"coverage": p["coverage"]})
    source = source.model_copy(update={"snapshot_commitment": m["internal_commitment"]})
    source = source.model_copy(
        update={"receipt_digest": hashlib.sha256(canonical(bundle["receipt"])).hexdigest()}
    )
    source = source.model_copy(
        update={"condition": "AVAILABLE" if result.status == "VALID" else "UNTRUSTED"}
    )
    source = source.model_copy(update={"proof_url": "/proof-vault?archive=" + sid})
    source = source.model_copy(
        update={"export_url": "/assurance-center/archives/" + sid + "/bundle"}
    )
    source = source.model_copy(
        update={"trace_url": "/x-ray?archive=" + sid if source.condition == "AVAILABLE" else None}
    )
    source = source.model_copy(
        update={
            "versions": [
                CenterVersion.model_validate(v)
                for v in m["configuration"].get("visible_version_bindings", [])
            ]
        }
    )
    corpus = {}
    try:
        if artifacts[0]["data"] is not None:
            corpus = json.loads(unb64(artifacts[0]["data"]))
        if not isinstance(corpus, dict):
            raise ValueError("OBJECT_REQUIRED")
        expected = {
            "assurance_report": "llm-assurance-v1",
            "resource_report": "resource-assurance-v1",
            "timing_report": "timing-mitigation-v1",
        }
        if entry.report_kind != "runtime":
            report = corpus.get(entry.report_kind, {})
            if report.get("schema_version") != expected[entry.report_kind]:
                source = source.model_copy(update={"condition": "STALE"})
            source = source.model_copy(
                update={"methodology": report.get("methodology") or report.get("schema_version")}
            )
        else:
            source = source.model_copy(update={"methodology": "nexus-proof-bundle-v1"})
    except (ValueError, TypeError, KeyError, AttributeError):
        source = source.model_copy(update={"condition": "STALE"})
        corpus = {}
    return (
        source,
        {
            "manifest": m,
            "events": events,
            "results": decimal_values(results),
            "corpus": corpus,
            "receipt": bundle["receipt"],
        },
        raw,
    )
