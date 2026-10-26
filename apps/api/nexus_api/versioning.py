"""Trusted local versioning implementation; no untrusted workload execution."""

import hashlib
import json
import uuid

from nexus_api.access import AccessError
from nexus_api.models import ArtifactVersion
from nexus_api.runtime_schemas import Domain as D
from nexus_api.runtime_schemas import MessageType as M

FLOWS = (
    (D.RED, D.MONITOR, M.ATTACK),
    (D.MONITOR, D.INPUT, M.INPUT_REQUEST),
    (D.INPUT, D.MONITOR, M.INPUT_RESULT),
    (D.MONITOR, D.MODEL, M.MODEL_REQUEST),
    (D.MODEL, D.MONITOR, M.MODEL_RESULT),
    (D.MONITOR, D.OUTPUT, M.OUTPUT_REQUEST),
    (D.OUTPUT, D.MONITOR, M.OUTPUT_RESULT),
    (D.MONITOR, D.RED, M.FINAL),
)
POLICY = {"version": "local-flow-v1", "default": "DENY", "flows": [list(f) for f in FLOWS]}


def canonical(value) -> bytes:
    # Preserve the legacy sorted JSON encoding and exact original version bytes,
    # including finite numeric spelling in versioned resource reports. No Unicode normalization.
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_version(db, owner_id, kind, content, artifact_id=None):
    try:
        data = canonical(content)
    except (UnicodeError, ValueError, TypeError):
        raise AccessError(
            422, "invalid_encoding", "Version must have canonical UTF-8 content"
        ) from None
    if len(data) > 65536:
        raise AccessError(422, "version_too_large", "Canonical version exceeds 65536 bytes")
    version_id = uuid.uuid4()
    domain = {"attack": "RED", "defence": "BLUE"}.get(kind, "INFRASTRUCTURE")
    record = ArtifactVersion(
        id=version_id,
        artifact_id=artifact_id,
        owner_id=owner_id,
        domain=domain,
        visibility={"RED": "RED_CONFIDENTIAL", "BLUE": "BLUE_CONFIDENTIAL"}.get(
            domain, "TRUSTED_INTERNAL"
        ),
        kind=kind,
        data=data,
        sha256=sha(data),
        byte_size=len(data),
        content_ref=f"db:version:{version_id}",
    )
    db.add(record)
    db.flush()
    return record


def verified_content(record):
    if record is None or len(record.data) != record.byte_size or sha(record.data) != record.sha256:
        raise ValueError("DIGEST_MISMATCH")
    value = json.loads(record.data)
    if canonical(value) != record.data:
        raise ValueError("NONCANONICAL_CONTENT")
    return value
