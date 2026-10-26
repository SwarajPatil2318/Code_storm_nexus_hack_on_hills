"""Frozen-threshold held-out analysis; missing trials are retained as unsuccessful."""

import math
import statistics


def wilson(correct, total):
    if not 0 <= correct <= total or total == 0:
        raise ValueError("INVALID_DENOMINATOR")
    z = 1.959963984540054
    p = correct / total
    den = 1 + z * z / total
    center = (p + z * z / (2 * total)) / den
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    return {"low": max(0, center - half), "high": min(1, center + half)}


def train(rows):
    if any(
        type(r["active"]) is not bool
        or (
            r["inference_ms"] is not None
            and (not math.isfinite(r["inference_ms"]) or r["inference_ms"] < 0)
        )
        for r in rows
    ):
        raise ValueError("INVALID_CALIBRATION")
    active = [r["inference_ms"] for r in rows if r["active"] and r["inference_ms"] is not None]
    idle = [r["inference_ms"] for r in rows if not r["active"] and r["inference_ms"] is not None]
    if min(len(active), len(idle)) < 3:
        raise ValueError("INSUFFICIENT_SEPARATE_CALIBRATION")
    a, b = statistics.median(active), statistics.median(idle)
    return {"threshold_ms": (a + b) / 2, "direction": "ABOVE" if a >= b else "BELOW"}


def analyze(rows, detector):
    if not rows or not any(r["active"] for r in rows) or not any(not r["active"] for r in rows):
        raise ValueError("BOTH_TRIAL_CONDITIONS_REQUIRED")
    counts = {
        "true_positive": 0,
        "true_negative": 0,
        "false_positive": 0,
        "false_negative": 0,
        "missing": 0,
    }
    for r in rows:
        value = r["inference_ms"]
        if value is None or not r.get("ground_truth_verified", True):
            counts["missing"] += 1
            continue
        if not math.isfinite(value) or value < 0:
            raise ValueError("INVALID_OBSERVATION")
        predicted = (
            value > detector["threshold_ms"]
            if detector["direction"] == "ABOVE"
            else value < detector["threshold_ms"]
        )
        key = (
            ("true_positive" if r["active"] else "false_positive")
            if predicted
            else ("false_negative" if r["active"] else "true_negative")
        )
        counts[key] += 1
    n = len(rows)
    correct = counts["true_positive"] + counts["true_negative"]
    tail = sum(math.comb(n, k) for k in range(correct, n + 1)) / 2**n
    inactive = sum(not r["active"] for r in rows)
    active = n - inactive
    return {
        **detector,
        **counts,
        "accuracy": correct / n,
        "accuracy_95": wilson(correct, n),
        "false_positive_rate": counts["false_positive"] / inactive if inactive else 0,
        "false_negative_rate": counts["false_negative"] / active if active else 0,
        "exact_binomial_tail": tail,
        "status": "FAIL" if tail <= 0.025 and not counts["missing"] else "INCONCLUSIVE",
    }
