"""Trusted preparation of one fixed, revision- and digest-pinned public CPU model/backend."""

import hashlib
import json
import os
import shutil
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".runtime"
MODEL_REVISION = "9217f5db79a29953eb74d5343926648285ec7e67"
MODEL_SHA = "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"
BACKEND_SHA = "8cb635bc20046c0aa75c623c8223c9b6b40bef8ecbc01dbce320eda48a72b5dd"


def verified(path, digest, size):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == digest


def download(url, path, digest, size):
    if verified(path, digest, size):
        return
    if shutil.disk_usage(STATE).free < size * 2 + 1073741824:
        raise SystemExit("INSUFFICIENT_MODEL_PREPARATION_DISK")
    partial = path.with_suffix(path.suffix + ".partial")
    deadline = time.monotonic() + 600
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "NEXUS-trusted-preparation"}
        )
        with (
            urllib.request.urlopen(request, timeout=45) as response,
            partial.open("wb") as out,
        ):
            total = 0
            while data := response.read(1024 * 1024):
                if time.monotonic() > deadline:
                    raise TimeoutError("ARTIFACT_DOWNLOAD_DEADLINE")
                total += len(data)
                if total > size:
                    raise ValueError("ARTIFACT_SIZE_MISMATCH")
                out.write(data)
        if not verified(partial, digest, size):
            raise ValueError("ARTIFACT_DIGEST_MISMATCH")
        partial.replace(path)
        os.chmod(path, 0o444)
    finally:
        partial.unlink(missing_ok=True)


def main():
    STATE.mkdir(mode=0o700, exist_ok=True)
    cache = STATE / "model-cache" / "qwen-0.5b"
    cache.mkdir(parents=True, exist_ok=True)
    download(
        f"https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/{MODEL_REVISION}/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        cache / "model.gguf",
        MODEL_SHA,
        491400032,
    )
    archive = STATE / "llama-b11731.tar.gz"
    download(
        "https://github.com/ggml-org/llama.cpp/releases/download/b11731/llama-b11731-bin-ubuntu-x64.tar.gz",
        archive,
        BACKEND_SHA,
        17974528,
    )
    extracted = STATE / "llama-extracted"
    extracted.mkdir(exist_ok=True)
    with tarfile.open(archive) as source:
        source.extractall(extracted, filter="data")
    binaries = STATE / "inference-bin"
    binaries.mkdir(exist_ok=True)
    server = next(extracted.rglob("llama-server"))
    (binaries / "llama-server").unlink(missing_ok=True)
    shutil.copy2(server, binaries / "llama-server")
    for library in server.parent.glob("lib*.so*"):
        if library.is_file():
            (binaries / library.name).unlink(missing_ok=True)
            shutil.copy2(library, binaries / library.name, follow_symlinks=True)
    os.chmod(binaries / "llama-server", 0o555)
    manifest = {
        "provider": "local",
        "model_id": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "revision": MODEL_REVISION,
        "artifact_sha256": MODEL_SHA,
        "artifact_size": 491400032,
        "tokenizer_revision": MODEL_REVISION,
        "family": "qwen2.5",
        "backend": "llama.cpp-b11731-cpu",
        "backend_archive_sha256": BACKEND_SHA,
        "resource_profile": "qwen-cpu-1g",
        "license": "Apache-2.0",
    }
    # Replace the immutable prepared metadata rather than writing through a read-only file.
    staged = cache / "manifest.json.partial"
    staged.unlink(missing_ok=True)
    try:
        staged.write_text(json.dumps(manifest, indent=2) + "\n")
        os.chmod(staged, 0o444)
        staged.replace(cache / "manifest.json")
    finally:
        staged.unlink(missing_ok=True)
    os.chmod(cache, 0o755)
    print(
        "Verified pinned Qwen GGUF and official CPU backend; no tenant download capability"
    )


if __name__ == "__main__":
    main()
