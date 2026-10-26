"""Pure runtime adapter contract and preserved trusted in-process fallback. No Docker access."""

import time

from nexus_api.runtime_schemas import Corpus, GuardConfig

SAFE = "Mock response: request handled."
WITHHELD = "Response withheld."


class InProcessRuntimeAdapter:
    isolated = False

    def __init__(self, contents, budget, check_cancel=lambda: None):
        self.corpus = Corpus.model_validate(contents[0])
        self.guard = GuardConfig.model_validate(contents[1])
        self.model = contents[2]
        self.budget = budget
        self.check_cancel = check_cancel

    def prepare(self):
        pass

    def red_case(self, index, correlation):
        return self.corpus.cases[index]

    def input_guard(self, value):
        approved = not self.guard.block_input and not any(
            t.casefold() in value.casefold() for t in self.guard.blocked_terms
        )
        return approved, value if approved else ""

    def inference(self, value):
        if self.model["mode"] == "error":
            raise ValueError("MOCK_MODEL_ERROR")
        if self.model["mode"] == "timeout":
            end = time.monotonic() + self.budget.model_timeout_ms / 1000
            while time.monotonic() < end:
                time.sleep(0.02)
                self.check_cancel()
            raise TimeoutError("MOCK_MODEL_TIMEOUT")
        return "CANARY_PRIVATE" if self.model["mode"] == "canary" else SAFE

    def output_guard(self, value, input_approved):
        approved = (
            input_approved
            and value == SAFE
            and not any(t.casefold() in value.casefold() for t in self.guard.blocked_terms)
        )
        return approved, SAFE if approved else WITHHELD

    def deliver(self, payload):
        pass

    def close(self):
        return True
