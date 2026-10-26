"""Unprivileged public API bootstrap. Startup secrets arrive via private stdin, never image/env."""

import json
import os
import pathlib
import sys

sys.path[:0] = ["/opt/nexus", "/opt/vendor"]
import uvicorn
from nexus_api.config import Settings
from nexus_api.main import create_app

if os.getuid() != 10001 or pathlib.Path("/var/run/docker.sock").exists():
    raise SystemExit("PUBLIC_API_CONFINEMENT_FAILED")
config = json.loads(sys.stdin.buffer.readline(32769))
settings = Settings(_env_file=None, **config)
uvicorn.run(create_app(settings), host="0.0.0.0", port=8000, access_log=False)
