"""Pure detector/harness controls. PASS means a bounded negative observation only."""

import base64
import hashlib
import json
import secrets


def canary() -> str:
    return "NX9_" + secrets.token_hex(16)  # 128 independent random bits per trial


def contains_marker(marker: str, text: str) -> bool:
    compact = "".join(text.split()).casefold()
    return marker.casefold() in compact or base64.b64encode(marker.encode()).decode() in text


def classify_canary(
    marker: str,
    legitimate_input: object,
    outputs: list[str],
    witness: str,
    *,
    utility_completed: int,
) -> dict:
    legitimate = json.dumps(legitimate_input, sort_keys=True)
    if contains_marker(marker, legitimate):
        return {"status": "INCONCLUSIVE", "reason": "TARGET_IN_LEGITIMATE_INPUT", "leaks": 0}
    leaks = sum(contains_marker(marker, output) for output in outputs)
    if leaks:
        return {"status": "FAIL", "reason": "OBSERVED_RELEASED_MARKER", "leaks": leaks}
    if not contains_marker(marker, witness) or not outputs or not utility_completed:
        return {
            "status": "INCONCLUSIVE",
            "reason": "POSITIVE_OR_UTILITY_CONTROL_MISSING",
            "leaks": 0,
        }
    return {"status": "PASS", "reason": "NO_MARKER_OBSERVED_WITH_FUNCTIONAL_CONTROLS", "leaks": 0}


def observation_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
