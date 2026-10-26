"""Trusted host launcher settings only; never accepted by the public API or tenants."""

import re


def port(value):
    number = int(value)
    if not 1024 <= number <= 65535:
        raise ValueError("UNPRIVILEGED_LOOPBACK_PORT_REQUIRED")
    return number


def name(value):
    if not re.fullmatch(r"nexus[a-z0-9_-]{0,58}", value):
        raise ValueError("NEXUS_HOST_RESOURCE_NAME_REQUIRED")
    return value
