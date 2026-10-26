"""Bounded, scoped HMAC transport shared by fixed gateway and workload images."""

import hashlib
import hmac
import json
import time
import uuid

LIMIT = 131072


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def sign(key, value):
    return hmac.new(bytes.fromhex(key), canonical(value), hashlib.sha256).hexdigest()


def frame(config, identity, action, payload, reply_to=None):
    return {
        "evaluation_id": config["evaluation_id"],
        "identity": identity,
        "action": action,
        "timestamp": int(time.time()),
        "nonce": uuid.uuid4().hex,
        "payload": payload,
        "reply_to": reply_to,
    }


def validate(config, value, signature, key, identity, actions, seen):
    if set(value) != {
        "evaluation_id",
        "identity",
        "action",
        "timestamp",
        "nonce",
        "payload",
        "reply_to",
    }:
        raise ValueError("SCHEMA_REJECTED")
    if (
        len(canonical(value)) > LIMIT
        or value["evaluation_id"] != config["evaluation_id"]
        or value["identity"] != identity
        or value["action"] not in actions
        or type(value["timestamp"]) is not int
        or abs(time.time() - value["timestamp"]) > 15
        or time.time() > config["expires_at"]
        or not isinstance(value["nonce"], str)
        or len(value["nonce"]) != 32
        or value["nonce"] in seen
        or not hmac.compare_digest(sign(key, value), signature)
    ):
        raise ValueError("IDENTITY_SCOPE_REJECTED")
    if len(seen) >= 10000:
        raise ValueError("REQUEST_LIMIT")
    seen.add(value["nonce"])
    return value["payload"]


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError("PAYLOAD_SCHEMA_REJECTED")


def text(value):
    if not isinstance(value, str) or len(value.encode()) > 8192:
        raise ValueError("TEXT_BOUND_REJECTED")
    return value
