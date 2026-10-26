"""Keep the reviewable OpenAPI snapshot synchronized with the application."""

import argparse
import json
from pathlib import Path

from nexus_api.config import Settings
from nexus_api.main import create_app

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
snapshot = root / "packages/contracts/openapi.json"
app = create_app(Settings(_env_file=None, environment="test", database_url=None))
rendered = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
if args.check:
    if not snapshot.exists() or snapshot.read_text() != rendered:
        raise SystemExit(
            "OpenAPI contract drift detected; run npm run contracts:generate"
        )
    print("OpenAPI snapshot matches the application")
else:
    snapshot.write_text(rendered)
    print("Exported packages/contracts/openapi.json")
