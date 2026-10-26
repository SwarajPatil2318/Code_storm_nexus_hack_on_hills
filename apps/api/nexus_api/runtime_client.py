"""Authenticated narrow Unix client. No Docker library, CLI, flags or daemon endpoint."""

import hashlib
import hmac
import json
import secrets
import socket
import time

from nexus_api.access import AccessError
from nexus_api.versioning import canonical


def control(settings, operation, evaluation_id, actor_id):
    if not settings.provisioner_socket or not settings.provisioner_key:
        raise AccessError(
            503, "isolated_unavailable", "Start the confined API and trusted provisioner profile"
        )
    body = {
        "operation": operation,
        "evaluation_id": str(evaluation_id),
        "actor_id": str(actor_id),
        "nonce": secrets.token_hex(16),
        "timestamp": int(time.time()),
    }
    key = bytes.fromhex(settings.provisioner_key.get_secret_value())
    value = {
        "request": body,
        "signature": hmac.new(key, canonical(body), hashlib.sha256).hexdigest(),
    }
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(5)
            connection.connect(settings.provisioner_socket)
            connection.sendall(canonical(value) + b"\n")
            raw = connection.makefile("rb").readline(131073)
        if len(raw) > 131072:
            raise ValueError
        result = json.loads(raw)
        signature = hmac.new(key, canonical(result["response"]), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, result["signature"]):
            raise ValueError
        response = result["response"]
        if response["nonce"] != body["nonce"]:
            raise ValueError
        if not response["ok"]:
            raise AccessError(
                response.get("status", 503),
                "runtime_rejected",
                "Trusted runtime rejected this operation",
            )
        return response["result"]
    except (OSError, ValueError, KeyError, TypeError):
        raise AccessError(503, "runtime_unavailable", "Trusted runtime is unavailable") from None
