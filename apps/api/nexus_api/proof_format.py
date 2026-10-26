"""Versioned Proof Vault formats. Pure bounded verification; no backend/DB access."""

import base64
import hashlib
import json
import math
from datetime import datetime
from typing import Annotated, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ConfigDict, Field

from nexus_api.schema_base import Strict

MAX_BUNDLE = 8 * 1024 * 1024
MAX_EVENTS = 8192
NAMES = ["manifest.json", "events.json", "artifacts.json", "results.json"]
HEX = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
UID = Annotated[str, Field(pattern=r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")]
STAMP = Annotated[str, Field(pattern=r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")]
Profile = Literal["INTERNAL", "RED_OPERATOR", "BLUE_OPERATOR", "AUDITOR"]
Coverage = Literal["FULL_INTERNAL_SNAPSHOT", "AUTHORIZED_PROJECTION_ONLY"]
Outcome = Literal["COMPLETED", "FAILED", "CANCELLED", "DESTROYED"]
Cleanup = Literal["VERIFIED", "FAILED", "PENDING", "NOT_STARTED", "IN_PROCESS_ONLY"]


def canonical(value):
    """RFC 8785 compatible safe-integer subset; not general floating point JCS."""

    def encode(v, depth=0):
        if depth > 32:
            raise ValueError("CANONICAL_DEPTH")
        if v is None or type(v) is bool:
            return json.dumps(v)
        if type(v) is int and abs(v) <= 9007199254740991:
            return str(v)
        if isinstance(v, str):
            v.encode("utf-8", "strict")
            return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        if isinstance(v, list):
            return "[" + ",".join(encode(x, depth + 1) for x in v) + "]"
        if isinstance(v, dict) and all(isinstance(k, str) for k in v):
            keys = sorted(v, key=lambda k: k.encode("utf-16-be", "strict"))
            return (
                "{"
                + ",".join(encode(k, depth + 1) + ":" + encode(v[k], depth + 1) for k in keys)
                + "}"
            )
        raise ValueError("CANONICAL_TYPE")

    return encode(value).encode("utf-8")


def measured(value):
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("NONFINITE_MEASUREMENT")
        from decimal import Decimal

        return {"decimal": format(Decimal(str(value)), "f")}
    if isinstance(value, dict):
        return {k: measured(v) for k, v in value.items()}
    if isinstance(value, list):
        return [measured(v) for v in value]
    return value


def pairs(items):
    d = {}
    for k, v in items:
        if k in d:
            raise ValueError("DUPLICATE_KEY")
        d[k] = v
    return d


def parse(raw):
    if len(raw) > MAX_BUNDLE:
        raise ValueError("SIZE_LIMIT")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE")),
        )
        if canonical(value) != raw:
            raise ValueError("NONCANONICAL")
        return value
    except (RecursionError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("MALFORMED_JSON") from error


def digest(kind, value):
    return hashlib.sha256(
        b"NEXUS-PROOF-V1\x00" + kind.encode("ascii") + b"\x00" + canonical(value)
    ).hexdigest()


def b64(raw):
    return base64.b64encode(raw).decode("ascii")


def unb64(value):
    raw = base64.b64decode(value, validate=True)
    if b64(raw) != value:
        raise ValueError("BINARY_ENCODING")
    return raw


def public_pem(key):
    return key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")


def key_id(pem):
    if not pem.startswith("-----BEGIN PUBLIC KEY-----\n"):
        raise ValueError("KEY_ENCODING")
    key = serialization.load_pem_public_key(pem.encode("ascii"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("KEY_ALGORITHM")
    return hashlib.sha256(
        key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    ).hexdigest()


class ProofStrict(Strict):
    model_config = ConfigDict(strict=True)


class Chain(ProofStrict):
    genesis: HEX
    terminal: HEX
    count: int = Field(ge=0, le=MAX_EVENTS, strict=True)
    first: int = Field(ge=0, le=1, strict=True)
    last: int = Field(ge=0, le=MAX_EVENTS, strict=True)
    source_sequences: list[int] = Field(max_length=MAX_EVENTS)


class Record(ProofStrict):
    format: Literal["nexus-event-v1"]
    evaluation_id: UID
    snapshot_id: UID
    event_id: UID
    sequence: int = Field(ge=1, le=MAX_EVENTS, strict=True)
    source_sequence: int = Field(ge=1, strict=True)
    event_type: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    source: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.:-]+$")
    destination: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.:-]+$")
    timestamp: STAMP
    correlation_id: UID
    visibility: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.:-]+$")
    payload: dict
    payload_digest: HEX
    previous_hash: HEX
    hash: HEX


class ArtifactOpening(ProofStrict):
    nonce: HEX
    version_id: UID
    kind: Literal["attack", "defence", "model", "flow_policy"]
    sha256: HEX
    byte_size: int = Field(ge=1, le=65536, strict=True)


class FileDigest(ProofStrict):
    name: Literal["manifest.json", "events.json", "artifacts.json", "results.json"]
    sha256: HEX
    size: int = Field(ge=0, le=MAX_BUNDLE, strict=True)


class ReceiptPayload(ProofStrict):
    format: Literal["nexus-receipt-v1"]
    key_id: HEX
    signed_at: STAMP
    snapshot_id: UID
    evaluation_id: UID
    profile: Profile
    subject_id: UID | None
    manifest_digest: HEX
    chain: Chain
    files: list[FileDigest] = Field(min_length=4, max_length=4)
    terminal_status: Outcome
    cleanup: Cleanup
    retrospective: bool
    coverage: Coverage


class Receipt(ProofStrict):
    payload: ReceiptPayload
    signature: str = Field(min_length=88, max_length=88)
    public_key: str = Field(max_length=160)


class BundleFile(ProofStrict):
    name: Literal["manifest.json", "events.json", "artifacts.json", "results.json"]
    content: str = Field(max_length=MAX_BUNDLE)


class Bundle(ProofStrict):
    format: Literal["nexus-proof-bundle-v1"]
    receipt: Receipt
    files: list[BundleFile] = Field(min_length=4, max_length=4)


class Manifest(ProofStrict):
    format: Literal["nexus-manifest-v1"]
    snapshot_id: UID
    evaluation_id: UID
    profile: Profile
    subject_id: UID | None
    frozen_at: STAMP
    source_watermark: int = Field(ge=0, le=MAX_EVENTS, strict=True)
    source_count: int = Field(ge=0, le=MAX_EVENTS, strict=True)
    chain: Chain
    terminal_status: Outcome
    cleanup: Cleanup
    retrospective: bool
    coverage: Coverage
    supersedes: UID | None
    internal_commitment: HEX
    configuration: dict
    artifact_commitments: list[HEX] = Field(min_length=4, max_length=4)
    disclosed_artifacts: list[Literal["attack", "defence", "model", "flow_policy"]] = Field(
        min_length=2, max_length=4
    )
    limitations: list[str] = Field(min_length=1, max_length=12)


class Verification(ProofStrict):
    status: Literal["VALID", "INVALID", "INCOMPLETE", "UNTRUSTED_SIGNER", "UNSUPPORTED_FORMAT"]
    category: str
    signature_valid: bool = False
    signer_trusted: bool = False
    evaluation_id: str | None = None
    snapshot_id: str | None = None
    coverage: Coverage | None = None
    full_internal_evidence_verified: bool = False
    terminal_status: str | None = None
    cleanup: str | None = None


def build_chain(records, context):
    previous = digest("genesis", context)
    genesis, output = previous, []
    for i, raw in enumerate(records, 1):
        value = {
            **raw,
            "format": "nexus-event-v1",
            "evaluation_id": context["evaluation_id"],
            "snapshot_id": context["snapshot_id"],
            "sequence": i,
            "payload_digest": digest("payload", raw["payload"]),
            "previous_hash": previous,
        }
        previous = digest("event", value)
        output.append({**value, "hash": previous})
    metadata = {
        "genesis": genesis,
        "terminal": previous,
        "count": len(output),
        "first": 1 if output else 0,
        "last": len(output),
        "source_sequences": [v["source_sequence"] for v in output],
    }
    return output, metadata


def signing_input(payload):
    return b"NEXUS-ED25519-RECEIPT-V1\x00" + canonical(payload)


def seal_bundle(manifest, events, artifacts, results, private_key, *, signed_at=None):
    values = [manifest, events, artifacts, results]
    raw_files = [canonical(v) for v in values]
    payload = {
        k: manifest[k]
        for k in [
            "snapshot_id",
            "evaluation_id",
            "profile",
            "subject_id",
            "chain",
            "terminal_status",
            "cleanup",
            "retrospective",
            "coverage",
        ]
    }
    payload.update(
        format="nexus-receipt-v1",
        key_id=key_id(public_pem(private_key.public_key())),
        signed_at=signed_at or manifest["frozen_at"],
        manifest_digest=digest("manifest", manifest),
        files=[
            {"name": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
            for name, raw in zip(NAMES, raw_files, strict=True)
        ],
    )
    ReceiptPayload.model_validate(payload)
    result = {
        "format": "nexus-proof-bundle-v1",
        "receipt": {
            "payload": payload,
            "signature": b64(private_key.sign(signing_input(payload))),
            "public_key": public_pem(private_key.public_key()),
        },
        "files": [{"name": n, "content": b64(v)} for n, v in zip(NAMES, raw_files, strict=True)],
    }
    raw = canonical(result)
    if len(raw) > MAX_BUNDLE:
        raise ValueError("SIZE_LIMIT")
    return raw


def verify(raw, trusted=None):
    category, signature_valid = "FORMAT", False
    try:
        data = parse(raw)
        if not isinstance(data, dict) or data.get("format") != "nexus-proof-bundle-v1":
            return Verification(status="UNSUPPORTED_FORMAT", category="FORMAT")
        if not isinstance(data.get("files"), list) or len(data["files"]) < 4:
            return Verification(status="INCOMPLETE", category="FILES")
        if data.get("receipt", {}).get("payload", {}).get("format") != "nexus-receipt-v1":
            return Verification(status="UNSUPPORTED_FORMAT", category="FORMAT")
        bundle = Bundle.model_validate(data)
        receipt = bundle.receipt.payload.model_dump()
        if len({f.name for f in bundle.files}) != 4 or [f.name for f in bundle.files] != NAMES:
            raise ValueError("FILES")
        if [f.name for f in bundle.receipt.payload.files] != NAMES:
            raise ValueError("FILES")
        category = "SIGNATURE"
        pem = bundle.receipt.public_key
        if key_id(pem) != receipt["key_id"]:
            raise ValueError("KEY_ID")
        key = serialization.load_pem_public_key(pem.encode("ascii"))
        key.verify(unb64(bundle.receipt.signature), signing_input(receipt))
        signature_valid = True
        category = "FILE_INTEGRITY"
        values = []
        for file, expected in zip(bundle.files, bundle.receipt.payload.files, strict=True):
            content = unb64(file.content)
            if (
                len(content) != expected.size
                or hashlib.sha256(content).hexdigest() != expected.sha256
            ):
                raise ValueError("FILE_DIGEST")
            values.append(parse(content))
        manifest, events, artifacts, results = values
        category = "MANIFEST"
        if manifest.get("format") != "nexus-manifest-v1":
            return Verification(
                status="UNSUPPORTED_FORMAT", category="MANIFEST", signature_valid=signature_valid
            )
        Manifest.model_validate(manifest)
        datetime.strptime(manifest["frozen_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        datetime.strptime(receipt["signed_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        if receipt["signed_at"] < manifest["frozen_at"]:
            raise ValueError("SIGNING_TIME")
        if digest("manifest", manifest) != receipt["manifest_digest"]:
            raise ValueError("MANIFEST_DIGEST")
        for k in [
            "evaluation_id",
            "snapshot_id",
            "profile",
            "subject_id",
            "chain",
            "terminal_status",
            "cleanup",
            "retrospective",
            "coverage",
        ]:
            if manifest[k] != receipt[k]:
                raise ValueError("MANIFEST_SCOPE")
        if manifest["source_count"] != manifest["source_watermark"]:
            raise ValueError("SOURCE_GAP")
        internal = manifest["profile"] == "INTERNAL"
        if (manifest["coverage"] == "FULL_INTERNAL_SNAPSHOT") != internal or (
            manifest["subject_id"] is None
        ) != internal:
            raise ValueError("COVERAGE")
        category = "CHAIN"
        context = {
            k: manifest[k]
            for k in ["evaluation_id", "snapshot_id", "profile", "subject_id", "source_watermark"]
        }
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise ValueError("EVENT_LIMIT")
        records = [Record.model_validate(v).model_dump() for v in events]
        if len({v["event_id"] for v in records}) != len(records):
            raise ValueError("DUPLICATE_EVENT")
        originals = []
        for v in records:
            datetime.strptime(v["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ")
            originals.append(
                {
                    k: value
                    for k, value in v.items()
                    if k
                    not in {
                        "format",
                        "evaluation_id",
                        "snapshot_id",
                        "sequence",
                        "payload_digest",
                        "previous_hash",
                        "hash",
                    }
                }
            )
        rebuilt, chain = build_chain(originals, context)
        if rebuilt != records or chain != manifest["chain"]:
            raise ValueError("CHAIN_MISMATCH")
        seq = chain["source_sequences"]
        if seq != sorted(set(seq)) or any(v > manifest["source_watermark"] for v in seq):
            raise ValueError("SEQUENCE")
        if internal and seq != list(range(1, manifest["source_watermark"] + 1)):
            raise ValueError("SOURCE_GAP")
        category = "ARTIFACT"
        if (
            not isinstance(artifacts, list)
            or len(artifacts) != 4
            or [x.get("kind") for x in artifacts] != ["attack", "defence", "model", "flow_policy"]
        ):
            raise ValueError("ARTIFACT_SET")
        opened = [a["kind"] for a in artifacts if a.get("opening") is not None]
        allowed = {
            "INTERNAL": {"attack", "defence", "model", "flow_policy"},
            "RED_OPERATOR": {"attack", "model", "flow_policy"},
            "BLUE_OPERATOR": {"defence", "model", "flow_policy"},
            "AUDITOR": {"model", "flow_policy"},
        }[manifest["profile"]]
        if (
            opened != manifest["disclosed_artifacts"]
            or not {"model", "flow_policy"}.issubset(opened)
            or not set(opened).issubset(allowed)
        ):
            raise ValueError("DISCLOSURE_SCOPE")
        legacy = manifest["configuration"].get("committed_manifest", {}) if internal else None
        expected_bindings = (
            legacy.get("versions", [])
            if internal
            else manifest["configuration"].get("visible_version_bindings", [])
        )
        if not isinstance(expected_bindings, list) or len(expected_bindings) != len(opened):
            raise ValueError("EXPECTED_ARTIFACTS")
        for artifact, commitment in zip(artifacts, manifest["artifact_commitments"], strict=True):
            if (
                set(artifact) != {"kind", "commitment", "opening", "data"}
                or artifact["commitment"] != commitment
            ):
                raise ValueError("ARTIFACT_FORMAT")
            opening = artifact["opening"]
            if opening is None:
                if artifact["data"] is not None or internal:
                    raise ValueError("ARTIFACT_MISSING")
                continue
            ArtifactOpening.model_validate(opening)
            if (
                set(opening) != {"nonce", "version_id", "kind", "sha256", "byte_size"}
                or opening["kind"] != artifact["kind"]
            ):
                raise ValueError("ARTIFACT_OPENING")
            if (
                not isinstance(opening["nonce"], str)
                or len(opening["nonce"]) != 64
                or any(c not in "0123456789abcdef" for c in opening["nonce"])
            ):
                raise ValueError("ARTIFACT_NONCE")
            if digest("artifact", opening) != commitment:
                raise ValueError("ARTIFACT_COMMITMENT")
            binding = {k: opening[k] for k in ["kind", "version_id", "sha256", "byte_size"]}
            if binding not in expected_bindings:
                raise ValueError("VERSION_BINDING")
            blob = unb64(artifact["data"])
            if (
                len(blob) != opening["byte_size"]
                or hashlib.sha256(blob).hexdigest() != opening["sha256"]
            ):
                raise ValueError("ARTIFACT_DIGEST")
        model_blob = unb64(artifacts[2]["data"])
        declared_model = legacy.get("model") if internal else manifest["configuration"].get("model")
        if declared_model is not None and canonical(json.loads(model_blob)) != canonical(
            declared_model
        ):
            raise ValueError("MODEL_BINDING")
        category = "RESULT"
        if (
            not isinstance(results, dict)
            or results.get("evaluation_id") != manifest["evaluation_id"]
            or results.get("terminal_status") != manifest["terminal_status"]
        ):
            raise ValueError("RESULT_SCOPE")
        if (
            internal
            and digest(
                "internal",
                {
                    "nonce": manifest["configuration"]["opening"],
                    "configuration": manifest["configuration"]["committed_manifest"],
                    "events": events,
                    "artifacts": artifacts,
                    "results": results,
                },
            )
            != manifest["internal_commitment"]
        ):
            raise ValueError("INTERNAL_COMMITMENT")
        category = "TRUST"
        entry = (trusted or {}).get(receipt["key_id"])
        trusted_signer = False
        if entry:
            trusted_signer = key_id(entry["public_key"]) == receipt["key_id"]
            at = receipt["signed_at"]
            datetime.strptime(at, "%Y-%m-%dT%H:%M:%S.%fZ")
            for field in ["activated_at", "retired_at"]:
                if entry.get(field):
                    datetime.strptime(entry[field], "%Y-%m-%dT%H:%M:%S.%fZ")
            if entry.get("activated_at") and at < entry["activated_at"]:
                trusted_signer = False
            if entry.get("retired_at") and at >= entry["retired_at"]:
                trusted_signer = False
        return Verification(
            status="VALID" if trusted_signer else "UNTRUSTED_SIGNER",
            category="COMPLETE" if trusted_signer else "TRUST",
            signature_valid=True,
            signer_trusted=trusted_signer,
            evaluation_id=manifest["evaluation_id"],
            snapshot_id=manifest["snapshot_id"],
            coverage=manifest["coverage"],
            full_internal_evidence_verified=internal and trusted_signer,
            terminal_status=manifest["terminal_status"],
            cleanup=manifest["cleanup"],
        )
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, InvalidSignature):
        return Verification(status="INVALID", category=category, signature_valid=signature_valid)
