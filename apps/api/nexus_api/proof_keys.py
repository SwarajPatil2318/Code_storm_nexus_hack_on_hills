"""Private-key custody is confined to the restricted evidence signer."""

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nexus_api.proof_format import key_id, public_pem

ROOT = next(
    (p for p in Path(__file__).resolve().parents if (p / "apps/api/nexus_api").is_dir()),
    Path("/opt/nexus"),
)


def private_file(path):
    path = Path(path)
    if (
        path.is_symlink()
        or any(p.is_symlink() for p in path.parents)
        or path.resolve().is_relative_to(ROOT)
        or path.resolve().is_relative_to(ROOT.parent / "Hack_on_Hills-release")
    ):
        raise ValueError("EXTERNAL_PRIVATE_KEY_PATH_REQUIRED")
    path.stat()  # Preserve an explicit missing-key failure before permission checks.
    if (
        not path.is_file()
        or path.stat().st_nlink != 1
        or path.stat().st_gid != os.getgid()
        or path.parent.stat().st_uid != os.getuid()
        or path.parent.stat().st_gid != os.getgid()
        or path.stat().st_mode & 0o077
        or path.parent.stat().st_mode & 0o077
        or path.stat().st_uid != os.getuid()
        or path.stat().st_size > 8192
    ):
        raise ValueError("PRIVATE_KEY_PERMISSIONS")
    return path


def load_key(path, keyring):
    key = serialization.load_pem_private_key(private_file(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("KEY_ALGORITHM")
    kid = key_id(public_pem(key.public_key()))
    entry = keyring.get(kid)
    if entry is None or entry.get("retired_at") or key_id(entry["public_key"]) != kid:
        raise ValueError("ACTIVE_KEY_REQUIRED")
    return key
