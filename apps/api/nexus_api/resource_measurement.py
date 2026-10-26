"""Declared descriptive statistics; no synthetic timings or universal security score."""

import math
import statistics

from nexus_api.resource_schemas import Distribution


def distribution(values, failures=0):
    if any(not math.isfinite(v) or v < 0 for v in values) or failures < 0:
        raise ValueError("Invalid measurement")
    ordered = sorted(values)
    return Distribution(
        samples=len(values) + failures,
        failures=failures,
        p50_ms=statistics.median(ordered) if ordered else None,
        p95_ms=ordered[math.ceil(0.95 * len(ordered)) - 1] if len(ordered) >= 20 else None,
        minimum_ms=min(ordered) if ordered else None,
        maximum_ms=max(ordered) if ordered else None,
    )


def jain(values):
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Invalid throughput")
    return sum(values) ** 2 / (len(values) * sum(v * v for v in values)) if any(values) else 0.0


def classify_timing(labels, timings, threshold):
    if not labels or len(labels) != len(timings) or any(type(v) is not bool for v in labels):
        raise ValueError("Invalid timing trial")
    if (
        not math.isfinite(threshold)
        or threshold < 0
        or any(not math.isfinite(t) or t < 0 for t in timings)
    ):
        raise ValueError("Invalid latency")
    predicted = [t > threshold for t in timings]
    correct = sum(a == b for a, b in zip(labels, predicted, strict=True))
    # Exploratory one-sided binomial comparison; dependence/confounding remains explicit.
    tail = sum(math.comb(len(labels), i) for i in range(correct, len(labels) + 1)) / 2 ** len(
        labels
    )
    return {
        "trials": len(labels),
        "active": sum(labels),
        "inactive": len(labels) - sum(labels),
        "correct": correct,
        "false_positives": sum(
            prediction and not label for label, prediction in zip(labels, predicted, strict=True)
        ),
        "status": "FAIL" if tail <= 0.05 and 0 < sum(labels) < len(labels) else "INCONCLUSIVE",
    }
