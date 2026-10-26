"""Explicit local-only identity provisioning; no bypass route and no embedded password."""

import argparse
import os
import secrets
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.auth import DEMO_IDENTITIES, hasher
from nexus_api.config import get_settings
from nexus_api.database import make_engine
from nexus_api.models import User

KEYS = [
    "NEXUS_DEMO_RED_PASSWORD",
    "NEXUS_DEMO_BLUE_PASSWORD",
    "NEXUS_DEMO_AUDITOR_PASSWORD",
    "NEXUS_DEMO_ADMIN_PASSWORD",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generate", action="store_true", help="Generate ignored local credentials"
    )
    args = parser.parse_args()
    settings = get_settings()
    if settings.environment != "development" or not settings.demo_auth_enabled:
        raise SystemExit("Demo provisioning requires development and NEXUS_DEMO_AUTH_ENABLED=true")
    path = Path(__file__).resolve().parents[1] / ".env.demo.local"
    if args.generate and not path.exists():
        content = "# Local development identities only. Never commit or deploy this file.\n"
        content += "\n".join(f"{key}={secrets.token_urlsafe(18)}" for key in KEYS) + "\n"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(content)
    values = {**dotenv_values(path), **os.environ}
    passwords = [values.get(key) or "" for key in KEYS]
    if any(len(password) < 12 for password in passwords):
        raise SystemExit("Provide four passwords of at least 12 characters, or use --generate")
    engine = make_engine(settings)
    if engine is None:
        raise SystemExit("Configure NEXUS_DATABASE_URL and migrate the database first")
    with Session(engine) as db:
        for identity, password in zip(DEMO_IDENTITIES, passwords, strict=True):
            user = db.scalar(select(User).where(User.email == identity.email))
            if user is None:
                user = User(
                    email=identity.email,
                    display_name=identity.display_name,
                    role=identity.role.value,
                    password_hash=hasher.hash(password),
                    is_demo=True,
                )
                db.add(user)
            elif not user.is_demo:
                raise SystemExit("Refusing to overwrite a non-demo identity")
            # Idempotent: never silently reset an existing user's password or role.
        db.commit()
    engine.dispose()
    print("Four demo identities are provisioned. Credentials: apps/api/.env.demo.local")
    print("Existing passwords are preserved; these users cannot authenticate in production.")


if __name__ == "__main__":
    main()
