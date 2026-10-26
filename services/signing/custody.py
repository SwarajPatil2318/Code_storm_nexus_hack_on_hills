"""Fixed key lifecycle commands inside an isolated container; never a network API."""

import base64
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from nexus_api.proof_format import key_id, public_pem
from nexus_api.proof_identity import KEY_PATH, SIGNER_GID, SIGNER_UID
from nexus_api.proof_keys import private_file

DIRECTORY = Path(KEY_PATH).parent
CHALLENGE = b"NEXUS-CUSTODY-SELFTEST-V1\x00"


def public(key):
    pem = public_pem(key.public_key())
    return {"key_id": key_id(pem), "public_key": pem}


def store(key):
    path = Path(KEY_PATH)
    if path.exists() or path.is_symlink():
        raise ValueError("EXISTING_KEY_PRESERVED")
    raw = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    with os.fdopen(fd, "wb") as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())
    directory = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    result = public(key)
    result["activated_at"] = (
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
    result["retired_at"] = None
    return result


def run(config):
    action = config["action"]
    if action == "prepare":
        if os.getuid() != 0 or any(DIRECTORY.iterdir()) or DIRECTORY.stat().st_uid != 0:
            raise ValueError("NEW_EMPTY_VOLUME_REQUIRED")
        DIRECTORY.chmod(0o700)
        os.chown(DIRECTORY, SIGNER_UID, SIGNER_GID)
        return {"prepared": True}
    if os.getuid() != SIGNER_UID or os.getgid() != SIGNER_GID:
        raise ValueError("DEDICATED_SIGNER_REQUIRED")
    info = DIRECTORY.stat()
    if (
        info.st_uid != SIGNER_UID
        or info.st_gid != SIGNER_GID
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("PRIVATE_KEY_DIRECTORY_REQUIRED")
    if action == "generate":
        return store(Ed25519PrivateKey.generate())
    if action == "restore":
        backup = config["backup"]
        if (
            set(backup) != {"format", "key_id", "public_key", "encrypted_pkcs8"}
            or backup["format"] != "nexus-key-backup-v1"
        ):
            raise ValueError("BACKUP_FORMAT")
        if (
            backup["key_id"] != config["expected_key_id"]
            or key_id(backup["public_key"]) != config["expected_key_id"]
        ):
            raise ValueError("INDEPENDENT_KEY_PIN_REQUIRED")
        key = serialization.load_pem_private_key(
            base64.b64decode(backup["encrypted_pkcs8"], validate=True),
            password=passphrase(config),
        )
        if (
            not isinstance(key, Ed25519PrivateKey)
            or public(key)["key_id"] != config["expected_key_id"]
        ):
            raise ValueError("RESTORED_KEY_ID_MISMATCH")
        store(key)
        # Recovery preserves the independently retained original trust interval.
        # A restoration timestamp must never replace original activation metadata.
        return {**public(key), "restored": True}
    key = serialization.load_pem_private_key(private_file(KEY_PATH).read_bytes(), None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("KEY_ALGORITHM")
    result = public(key)
    if result["key_id"] != config["expected_key_id"]:
        raise ValueError("INDEPENDENT_KEY_PIN_REQUIRED")
    if action == "backup":
        encrypted = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(passphrase(config)),
        )
        return {
            "format": "nexus-key-backup-v1",
            **result,
            "encrypted_pkcs8": base64.b64encode(encrypted).decode(),
        }
    if action == "selftest":
        result["signature"] = base64.b64encode(key.sign(CHALLENGE)).decode()
        return result
    raise ValueError("UNKNOWN_CUSTODY_ACTION")


def passphrase(config):
    raw = base64.b64decode(config["passphrase"], validate=True)
    if not 20 <= len(raw) <= 1023:
        raise ValueError("RECOVERY_PASSPHRASE_LENGTH")
    return raw


if __name__ == "__main__":
    import sys

    try:
        data = sys.stdin.buffer.readline(65537)
        if len(data) > 65536:
            raise ValueError("INPUT_LIMIT")
        print(json.dumps(run(json.loads(data))))
    except Exception as error:  # noqa: BLE001 - never disclose key/passphrase/configuration
        print(
            json.dumps(
                {
                    "error": "CUSTODY_OPERATION_REJECTED",
                    "exception_type": type(error).__name__,
                }
            )
        )
        raise SystemExit(1) from None
