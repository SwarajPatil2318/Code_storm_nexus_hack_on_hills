"""Trusted local model cache/image validation; never accepts operator paths or URLs."""

import hashlib
import json
import os
from pathlib import Path

from nexus_api.campaign_schemas import (
    BACKEND_SHA,
    QWEN_ID,
    QWEN_REVISION,
    QWEN_SHA,
    ModelManifest,
)

from services.orchestrator.engine import MODEL_STATE, image_id


def local_runtime(*, verify_artifact=False):
    registry = Path(os.environ.get("NEXUS_MODEL_REGISTRY_DIR", MODEL_STATE))
    record = json.loads((registry / "model-runtime.json").read_text())
    image_id(record["image"])
    expected = {
        "provider": "local",
        "model_id": QWEN_ID,
        "revision": QWEN_REVISION,
        "artifact_sha256": QWEN_SHA,
        "artifact_size": 491400032,
        "tokenizer_revision": QWEN_REVISION,
        "family": "qwen2.5",
        "backend": "llama.cpp-b11731-cpu",
        "backend_archive_sha256": BACKEND_SHA,
        "resource_profile": "qwen-cpu-1g",
        "license": "Apache-2.0",
    }
    if {key: value for key, value in record.items() if key != "image"} != expected:
        raise ValueError("MODEL_ALLOWLIST_MISMATCH")
    cache = MODEL_STATE / "model-cache/qwen-0.5b"
    artifact = cache / "model.gguf"
    if cache.resolve() != cache or artifact.is_symlink() or not artifact.is_file():
        raise ValueError("MODEL_ARTIFACT_MISSING")
    metadata = cache / "manifest.json"
    if (
        {entry.name for entry in cache.iterdir()} != {"model.gguf", "manifest.json"}
        or metadata.is_symlink()
        or json.loads(metadata.read_text()) != expected
    ):
        raise ValueError("MODEL_CACHE_MANIFEST_MISMATCH")
    if artifact.stat().st_size != 491400032:
        raise ValueError("MODEL_ARTIFACT_SIZE_MISMATCH")
    if verify_artifact:
        with artifact.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != QWEN_SHA:
                raise ValueError("MODEL_ARTIFACT_DIGEST_MISMATCH")
    return record


def approved_images(base, model, *, verify_artifact=False):
    if model.get("schema_version") != "model-manifest-v1":
        return base
    manifest = ModelManifest.model_validate(model)
    if manifest.provider == "local":
        runtime = local_runtime(verify_artifact=verify_artifact)
        return {**base, "model": runtime["image"]}
    return base
