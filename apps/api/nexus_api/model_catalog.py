"""Provider allowlist and immutable manifests; no caller endpoint or backend selection."""

from nexus_api.campaign_schemas import (
    BACKEND_SHA,
    QWEN_ID,
    QWEN_REVISION,
    QWEN_SHA,
    Generation,
    ModelManifest,
)


def model_manifest(provider, generation=None, *, isolated=True, mock_mode="safe"):
    settings = generation or Generation()
    common = {
        "generation": settings,
        "isolation": "isolated_container" if isolated else "in_process",
        "mock_mode": mock_mode,
    }
    if provider == "mock":
        return ModelManifest(
            provider="mock",
            model_id="mock-v1",
            revision="1",
            tokenizer_revision="none",
            family="deterministic",
            resource_profile="mock-128m",
            backend="deterministic-v1",
            **common,
        )
    if provider == "local":
        return ModelManifest(
            provider="local",
            model_id=QWEN_ID,
            revision=QWEN_REVISION,
            artifact_sha256=QWEN_SHA,
            tokenizer_revision=QWEN_REVISION,
            family="qwen2.5",
            resource_profile="qwen-cpu-1g",
            backend="llama.cpp-b11731-cpu",
            backend_sha256=BACKEND_SHA,
            **common,
        )
    raise ValueError("PROVIDER_NOT_ALLOWLISTED")
