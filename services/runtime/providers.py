"""Fixed inference providers inside the model security domain; no caller-selected endpoints."""

import hashlib
import http.client
import json
import pathlib
import subprocess
import time

MODEL_SHA = "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"


class ProviderError(Exception):
    pass


def validate_messages(messages):
    if not isinstance(messages, list) or not 2 <= len(messages) <= 6:
        raise ProviderError("INVALID_CONVERSATION")
    total = 0
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise ProviderError("INVALID_CONVERSATION")
        if message["role"] not in ({"system"} if index == 0 else {"user", "assistant"}):
            raise ProviderError("INVALID_CONVERSATION")
        if not isinstance(message["content"], str):
            raise ProviderError("INVALID_CONVERSATION")
        total += len(message["content"].encode())
    if total > 3400:
        raise ProviderError("PROMPT_SIZE_EXCEEDED")


class DeterministicMockProvider:
    label = "MOCK"

    def __init__(self, manifest):
        self.manifest = manifest
        self.load_duration_ms = 0

    def infer(self, messages, timeout_ms):
        validate_messages(messages)
        start = time.monotonic()
        mode = self.manifest["mock_mode"]
        if mode == "error":
            raise ProviderError("MOCK_MODEL_ERROR")
        if mode == "timeout":
            time.sleep(min(timeout_ms / 1000, 1))
            raise TimeoutError("MODEL_TIMEOUT")
        return {
            "text": "NEXUS_SYNTH_CANARY_V1"
            if mode == "canary"
            else "Mock response: request handled.",
            "duration_ms": int((time.monotonic() - start) * 1000),
            "prompt_tokens": None,
            "completion_tokens": None,
            "finish_reason": "mock",
        }


class LocalModelProvider:
    label = "LOCAL MODEL"

    def __init__(self, manifest):
        self.manifest = manifest
        start = time.monotonic()
        model = pathlib.Path("/opt/model/model.gguf")
        if model.is_symlink() or not model.is_file():
            raise ProviderError("MODEL_ARTIFACT_MISSING")
        with model.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != MODEL_SHA or manifest["artifact_sha256"] != MODEL_SHA:
            raise ProviderError("MODEL_ARTIFACT_DIGEST_MISMATCH")
        self.process = subprocess.Popen(
            [
                "/opt/inference/llama-server",
                "--model",
                str(model),
                "--host",
                "127.0.0.1",
                "--port",
                "9000",
                "--ctx-size",
                "2048",
                "--threads",
                "2",
                "--threads-batch",
                "2",
                "--parallel",
                "1",
                "--no-cache-prompt",
                "--cache-ram",
                "0",
                "--no-cache-idle-slots",
                "--cache-reuse",
                "0",
                "--no-slots",
                "--n-gpu-layers",
                "0",
                "--offline",
                "--log-disable",
                "--no-webui",
                "--alias",
                "nexus-approved-qwen",
                "--seed",
                "42",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(300):
                if self.process.poll() is not None:
                    raise ProviderError("MODEL_LOAD_FAILED")
                try:
                    self._request("GET", "/health", None, 1)
                    break
                except (OSError, ValueError, ProviderError):
                    time.sleep(0.1)
            else:
                raise TimeoutError("MODEL_LOAD_TIMEOUT")
            # A live process is insufficient readiness evidence: generate an actual token.
            warmup = self._complete(
                [
                    {"role": "system", "content": "You are a concise assistant."},
                    {"role": "user", "content": "Reply with the word ready."},
                ],
                1,
                10000,
            )
            if not warmup["text"] or not warmup["completion_tokens"]:
                raise ProviderError("MODEL_READINESS_INFERENCE_FAILED")
            self.readiness_tokens = warmup["completion_tokens"]
            self.load_duration_ms = int((time.monotonic() - start) * 1000)
        except Exception:
            self.process.terminate()
            self.process.wait(timeout=5)
            raise

    def _request(self, method, path, payload, timeout):
        connection = http.client.HTTPConnection("127.0.0.1", 9000, timeout=timeout)
        try:
            data = json.dumps(payload).encode() if payload is not None else None
            connection.request(method, path, data, {"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(65537)
            if len(raw) > 65536 or response.status != 200:
                raise ProviderError("MODEL_BACKEND_REJECTED")
            return json.loads(raw)
        finally:
            connection.close()

    def _complete(self, messages, max_tokens, timeout_ms):
        start = time.monotonic()
        value = self._request(
            "POST",
            "/v1/chat/completions",
            {
                "model": "nexus-approved-qwen",
                "messages": messages,
                "temperature": 0,
                "seed": self.manifest["generation"]["seed"],
                "max_tokens": max_tokens,
                "stream": False,
                "cache_prompt": False,
            },
            timeout_ms / 1000,
        )
        try:
            output = value["choices"][0]["message"]["content"]
            reason = value["choices"][0]["finish_reason"]
            usage = value.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            if not isinstance(output, str) or len(output.encode()) > 4096:
                raise ValueError
            for count in (prompt_tokens, completion_tokens):
                if count is not None and (type(count) is not int or count < 0):
                    raise ValueError
            if completion_tokens is not None and completion_tokens > max_tokens:
                raise ValueError
            if reason not in {"length", "stop"}:
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("MALFORMED_MODEL_RESPONSE") from None
        return {
            "text": output,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "finish_reason": reason,
        }

    def infer(self, messages, timeout_ms):
        validate_messages(messages)
        if type(timeout_ms) is not int or not 20 <= timeout_ms <= 60000:
            raise ProviderError("INVALID_TIMEOUT")
        return self._complete(
            messages, self.manifest["generation"]["max_output_tokens"], timeout_ms
        )
