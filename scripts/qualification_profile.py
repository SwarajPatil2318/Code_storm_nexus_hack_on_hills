"""Validated names and loopback ports for disposable qualification copies."""

import os
import re
from dataclasses import dataclass
from pathlib import Path


def validate_qualification_path(root: Path) -> None:
    path = root / ".runtime/ui-qa/control/provisioner.sock"
    if len(os.fsencode(path)) >= 108:
        raise ValueError("QUALIFICATION_PATH_TOO_LONG_USE_A_SHORT_WORKSPACE")


@dataclass(frozen=True)
class QualificationProfile:
    project: str
    scope: str
    role_prefix: str
    api_port: int
    web_port: int
    database_port: int


def qualification_profile(
    instance: str | None,
    api_port: int | None = None,
    web_port: int | None = None,
    database_port: int | None = None,
) -> QualificationProfile:
    ports = (api_port, web_port, database_port)
    if instance is None:
        if any(p is not None for p in ports):
            raise ValueError("CUSTOM_PORTS_REQUIRE_EXPLICIT_INSTANCE")
        return QualificationProfile(
            "nexus-m13-clean", "m13clean", "m13_clean", 8028, 3028, 55439
        )
    if not re.fullmatch(r"[a-z][a-z0-9]{2,19}", instance):
        raise ValueError("INSTANCE_REQUIRES_3_TO_20_LOWERCASE_ALPHANUMERIC_CHARACTERS")
    if any(type(p) is not int or not 1024 <= p <= 65535 for p in ports):
        raise ValueError("INSTANCE_REQUIRES_THREE_EXPLICIT_UNPRIVILEGED_PORTS")
    if len(set(ports)) != 3:
        raise ValueError("QUALIFICATION_PORTS_MUST_BE_DISTINCT")
    return QualificationProfile(
        "nexus-qual-" + instance,
        "qual" + instance,
        "qual_" + instance,
        api_port,
        web_port,
        database_port,
    )
