"""Local NEXUS lifecycle using the existing isolated instance launcher."""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["prepare-model", "setup", "start", "status", "stop"]
    )
    parser.add_argument("--instance", default="localdev")
    parser.add_argument("--web-port", type=int, default=3000)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--database-port", type=int, default=55432)
    parser.add_argument("--model-state", type=Path)
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12 or newer is required")
    environment = {**os.environ, "PYTHONPATH": f"{root / 'apps/api'}:{root}"}
    if args.action == "prepare-model":
        if args.model_state:
            parser.error(
                "prepare-model writes verified artifacts to this checkout's .runtime"
            )
        command = [sys.executable, str(root / "scripts/prepare_model.py")]
    else:
        command = [
            sys.executable,
            str(root / "scripts/qualify_submission.py"),
            args.action,
            "--instance",
            args.instance,
            "--api-port",
            str(args.api_port),
            "--web-port",
            str(args.web_port),
            "--database-port",
            str(args.database_port),
            "--model-state",
            str((args.model_state or root / ".runtime").resolve()),
        ]
    result = subprocess.run(command, cwd=root, env=environment, check=False)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
