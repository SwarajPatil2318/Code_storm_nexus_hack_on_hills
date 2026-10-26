"""Restricted polling signer. No network listener, Docker access or arbitrary signing input."""

import argparse
import json
import logging
import os
import signal
import threading
from pathlib import Path

from nexus_api.config import Settings
from nexus_api.database import SCHEMA_REVISION, make_engine
from nexus_api.database_security import validate_runtime
from nexus_api.models import EvidenceKey, EvidenceRequest
from nexus_api.proof_format import key_id, public_pem
from nexus_api.proof_identity import SIGNER_GID, SIGNER_UID
from nexus_api.proof_keys import load_key
from nexus_api.proof_service import finalize, timestamp
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.orm import Session


def run(config, once=False):
    if os.getuid() != SIGNER_UID or os.getgid() != SIGNER_GID:
        raise ValueError("DEDICATED_SIGNER_IDENTITY_REQUIRED")
    settings = Settings(_env_file=None, database_url=SecretStr(config["database_url"]))
    engine = make_engine(settings)
    ring = config["trusted_keys"]
    key = load_key(Path(config["private_key"]), ring)
    kid = key_id(public_pem(key.public_key()))
    entry = ring[kid]
    if timestamp() < entry["activated_at"]:
        raise ValueError("KEY_NOT_ACTIVE")
    with engine.begin() as db:
        validate_runtime(db)
        if (
            db.scalar(text("SELECT version_num FROM alembic_version"))
            != SCHEMA_REVISION
        ):
            raise ValueError("MIGRATION_REQUIRED")
    with Session(engine) as db, db.begin():
        if db.get(EvidenceKey, kid) is None:
            db.add(
                EvidenceKey(
                    key_id=kid,
                    public_key=entry["public_key"],
                    activated_at=entry["activated_at"],
                    retired_at=None,
                )
            )
    stop = threading.Event()
    if threading.current_thread() is threading.main_thread():
        for sig in [signal.SIGTERM, signal.SIGINT]:
            signal.signal(sig, lambda *_: stop.set())
    print("Restricted evidence signer ready; no public endpoint", flush=True)
    while not stop.is_set():
        with Session(engine) as db:
            pending = list(
                db.scalars(
                    select(EvidenceRequest.id)
                    .where(EvidenceRequest.state == "PENDING")
                    .order_by(EvidenceRequest.created_at)
                    .limit(8)
                )
            )
        for rid in pending:
            try:
                finalize(
                    engine,
                    rid,
                    key,
                    ring,
                    lock_dir=config["lock_dir"],
                    owner=config["runtime_owner"],
                    runtime_uid=config["runtime_uid"],
                )
            except (ValueError, KeyError):
                with Session(engine) as db, db.begin():
                    row = db.get(EvidenceRequest, rid)
                    if row and row.state == "PENDING":
                        row.state, row.reason_code = (
                            "FAILED",
                            "EVIDENCE_INCOMPLETE_OR_KEY_UNAVAILABLE",
                        )
                logging.getLogger("nexus.signer").warning(
                    "evidence_finalization_rejected"
                )
            except Exception as error:  # noqa: BLE001 - suppress private failure values
                # A DB outage/interruption leaves the queue retryable; no partial receipt commits.
                logging.getLogger("nexus.signer").warning(
                    "evidence_signing_retry",
                    extra={"exception_type": type(error).__name__},
                )
        if once:
            break
        stop.wait(1)
    engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.config.is_symlink() or args.config.stat().st_mode & 0o077:
        raise SystemExit("PRIVATE_SIGNER_CONFIG_REQUIRED")
    try:
        run(json.loads(args.config.read_text()), args.once)
    except Exception:  # noqa: BLE001 - suppress private failure values
        raise SystemExit(
            "SIGNER_START_FAILED; private configuration/key/privileges required"
        ) from None


if __name__ == "__main__":
    main()
