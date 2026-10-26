"""In-process campaign MOCK adapter; deliberately cannot run a real provider."""

import time

from nexus_api.campaign_schemas import AttackCase, ModelManifest
from nexus_api.evaluation_rules import guard_input, guard_output


class CampaignMockAdapter:
    isolated = False

    def __init__(
        self,
        contents,
        budget,
        *,
        campaign,
        check_cancel=lambda: None,
        on_model_event=lambda *_: None,
    ):
        self.contents, self.budget, self.campaign = contents, budget, campaign
        self.check_cancel, self.on_model_event = check_cancel, on_model_event
        model = ModelManifest.model_validate(contents[2])
        if model.provider != "mock":
            raise ValueError("REAL_PROVIDER_REQUIRES_ISOLATION")
        self.model = model

    def prepare(self):
        self.on_model_event("MODEL_LOADING", {})
        self.on_model_event("MODEL_READY", {"duration_ms": 0})

    def campaign_case(self, index, correlation):
        return AttackCase.model_validate(self.contents[0]["cases"][index])

    def campaign_guard(self, stage, value):
        return (guard_input if stage == "input" else guard_output)(
            value, self.contents[1], self.campaign["arm"]
        )

    def campaign_inference(self, messages, correlation, *, timeout_ms=None):
        start = time.monotonic()
        if self.model.mock_mode == "error":
            raise ValueError("MOCK_MODEL_ERROR")
        if self.model.mock_mode == "timeout":
            end = start + (timeout_ms or self.budget.model_timeout_ms) / 1000
            while time.monotonic() < end:
                self.check_cancel()
                time.sleep(0.02)
            raise TimeoutError("MODEL_TIMEOUT")
        return {
            "text": "NEXUS_SYNTH_CANARY_V1"
            if self.model.mock_mode == "canary"
            else "Mock response: request handled.",
            "duration_ms": int((time.monotonic() - start) * 1000),
            "prompt_tokens": None,
            "completion_tokens": None,
            "finish_reason": "mock",
        }

    def deliver(self, payload):
        pass

    def close(self):
        return True
