"""Scoped assurance QA using existing launchers, separate schema/owner/config/images.

No M8 or normal service is restarted. Model weights remain shared read-only.
Runtime roles and claims are independent; QA schema/history persist for review.
"""

import argparse
import json
import os
import secrets
import sys
from uuid import uuid4

from dotenv import dotenv_values
from nexus_api.auth import DEMO_IDENTITIES, hasher
from nexus_api.models import User
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from scripts import demo
from scripts.configure_database import configure
from scripts.proof_custody import create, operation
from scripts.provision_signer import provision
from scripts.verify_backup import capture

ROOT = demo.ROOT
PROFILE = os.environ.get("NEXUS_QA_PROFILE", "llm")
if PROFILE not in {"llm", "resource", "timing", "center", "ui"}:
    raise ValueError("UNKNOWN_QA_PROFILE")
SCOPE = {
    "llm": "m9",
    "resource": "m10",
    "timing": "m101",
    "center": "m11",
    "ui": "m12",
}[PROFILE]
API_PORT, WEB_PORT = {
    "llm": (8009, 3009),
    "resource": (8010, 3010),
    "timing": (8011, 3011),
    "center": (8012, 3012),
    "ui": (8013, 3013),
}[PROFILE]
STATE = (
    ROOT
    / (
        {
            "llm": ".runtime/llm-assurance",
            "resource": ".runtime/resource-assurance",
            "timing": ".runtime/timing-mitigation",
            "center": ".runtime/assurance-center",
            "ui": ".runtime/ui-qa",
        }[PROFILE]
    )
)
ORIGINAL_ENV = demo.env


def environment():
    return {
        **ORIGINAL_ENV(),
        "NEXUS_RUNTIME_STATE_DIR": str(STATE),
        "NEXUS_MODEL_REGISTRY_DIR": str(STATE),
        "NEXUS_CONFIG_FILE": str(STATE / "api.env"),
        "NEXUS_ASSURANCE_WEB": "1" if PROFILE == "llm" else "0",
        "NEXUS_RESOURCE_WEB": "1" if PROFILE == "resource" else "0",
        "NEXUS_TIMING_WEB": "1" if PROFILE == "timing" else "0",
        "NEXUS_QA_PROFILE": PROFILE,
        "NEXUS_UI_WEB": "1" if PROFILE == "ui" else "0",
        "NEXUS_CENTER_WEB": "1" if PROFILE == "center" else "0",
        "NEXT_PUBLIC_API_URL": demo.API,
        "NEXUS_API_INTERNAL_URL": demo.API,
    }


def select_instance():
    demo.STATE, demo.API, demo.WEB = (
        STATE,
        f"http://127.0.0.1:{API_PORT}",
        f"http://127.0.0.1:{WEB_PORT}",
    )
    demo.API_NAME, demo.SIGNER_NAME = (
        f"nexus-{SCOPE}-qa-api",
        f"nexus-{SCOPE}-qa-signer",
    )
    demo.env = environment


def instance_snapshot(name):
    config = json.loads(
        (ROOT / ".runtime" / name / "database.secrets.json").read_bytes()
    )
    return {
        "database": capture(config["admin_url"], schema=config["schema"]),
        "files": {
            filename: (ROOT / ".runtime" / name / filename).read_text()
            for filename in [
                "api-image",
                "signer-image",
                "owner",
                "trust.json",
                "web.process.json",
                "api.process.json",
                "signer.process.json",
                "provisioner.process.json",
            ]
        },
    }


def m9_snapshot():
    return instance_snapshot("llm-assurance")


def baseline_name():
    return (
        "qa-preservation-before.json"
        if PROFILE in {"timing", "center", "ui"}
        else "preservation-before.json"
    )


def baseline():
    if (STATE / baseline_name()).exists():
        return
    normal = demo.normal_snapshot()
    demo_url = json.loads(
        (ROOT / ".runtime/proof-demo/database.secrets.json").read_bytes()
    )["admin_url"]
    demo.private(
        baseline_name(),
        {
            "normal": normal,
            **(
                {"m9": m9_snapshot()}
                if PROFILE in {"resource", "timing", "center", "ui"}
                else {}
            ),
            **(
                {"m10": instance_snapshot("resource-assurance")}
                if PROFILE in {"timing", "center", "ui"}
                else {}
            ),
            **(
                {"m101": instance_snapshot("timing-mitigation")}
                if PROFILE in {"center", "ui"}
                else {}
            ),
            **(
                {"m11": instance_snapshot("assurance-center")}
                if PROFILE == "ui"
                else {}
            ),
            "m8": capture(demo_url),
            "m8_images": {
                name: (ROOT / ".runtime/proof-demo" / name).read_text()
                for name in ["api-image", "signer-image", "owner"]
            },
        },
    )


def initialize():
    baseline()
    if (STATE / "initialized").exists():
        return
    if not (STATE / "owner").exists():
        demo.private("owner", str(uuid4()))
    if not (STATE / "database.secrets.json").exists():
        parent = json.loads(
            (ROOT / ".runtime/proof-demo/database.secrets.json").read_bytes()
        )
        schema = SCOPE + "_assurance_" + uuid4().hex[:10]
        demo.private(
            "database.secrets.json",
            {
                "admin_url": make_url(parent["admin_url"])
                .set(query={"options": "-csearch_path=" + schema})
                .render_as_string(hide_password=False),
                "schema": schema,
                "roles": {
                    k: SCOPE + "_" + schema[-10:] + "_" + k
                    for k in ["api", "migrator", "provisioner"]
                },
                "passwords": {
                    k: secrets.token_hex(24)
                    for k in ["api", "migrator", "provisioner", "signer"]
                },
            },
        )
    config = demo.read("database.secrets.json")
    configure(config, STATE / "api.env")
    engine = create_engine(config["admin_url"], hide_parameters=True)
    role = SCOPE + "_" + config["schema"][-10:] + "_signer"
    try:
        with engine.connect() as connection:
            exists = connection.scalar(
                text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:name)"),
                {"name": role},
            )
        if not exists:
            provision(engine, config["schema"], role, config["passwords"]["signer"])
    finally:
        engine.dispose()
    for script, args in [
        ("build_runtime.py", ["--tag-prefix", f"nexus-{SCOPE}"]),
        ("build_model_image.py", ["--tag", f"nexus-{SCOPE}-local-model:{SCOPE}"]),
        ("build_api_image.py", ["--tag", f"nexus-{SCOPE}-qa-api:{SCOPE}"]),
        ("build_signer_image.py", ["--tag", f"nexus-{SCOPE}-qa-signer:{SCOPE}"]),
    ]:
        demo.run([sys.executable, ROOT / "scripts" / script, *args], timeout=600)
    owner = (STATE / "owner").read_text().strip()
    image = (STATE / "signer-image").read_text().strip()
    volume = f"nexus-{SCOPE}-qa-key-" + config["schema"][-10:]
    create(volume, image, owner, test=True)
    public = operation(volume, image, {"action": "generate"}, writable=True)
    ring = {
        public["key_id"]: {
            k: public[k] for k in ["public_key", "activated_at", "retired_at"]
        }
    }
    demo.private("trust.json", ring)
    demo.private(
        "signer.secrets.json",
        {
            "database_url": make_url(config["admin_url"])
            .set(username=role, password=config["passwords"]["signer"])
            .render_as_string(hide_password=False),
            "key_volume": volume,
            "trusted_keys": ring,
        },
    )
    with (STATE / "api.env").open("a") as file:
        file.write("NEXUS_DEMO_AUTH_ENABLED=true\nNEXUS_ENVIRONMENT=development\n")
        file.write("NEXUS_CORS_ORIGINS='" + json.dumps([demo.WEB]) + "'\n")
        file.write("NEXUS_PROOF_TRUSTED_KEYS='" + json.dumps(ring) + "'\n")
    credentials = {
        f"NEXUS_DEMO_{r}_PASSWORD": secrets.token_urlsafe(24)
        for r in ["RED", "BLUE", "AUDITOR", "ADMIN", "ATTACKER"]
    }
    demo.private(
        "credentials.env", "\n".join(f"{k}={v}" for k, v in credentials.items()) + "\n"
    )
    engine = create_engine(
        dotenv_values(STATE / "api.env")["NEXUS_DATABASE_URL"], hide_parameters=True
    )
    try:
        with Session(engine) as db:
            for identity, role in zip(
                DEMO_IDENTITIES, ["RED", "BLUE", "AUDITOR", "ADMIN"], strict=True
            ):
                db.add(
                    User(
                        email=identity.email,
                        display_name=identity.display_name,
                        role=identity.role.value,
                        is_demo=True,
                        password_hash=hasher.hash(
                            credentials[f"NEXUS_DEMO_{role}_PASSWORD"]
                        ),
                    )
                )
            db.add(
                User(
                    email="attacker@nexus.local",
                    display_name="Independent test attacker",
                    role="RED_OPERATOR",
                    is_demo=True,
                    password_hash=hasher.hash(
                        credentials["NEXUS_DEMO_ATTACKER_PASSWORD"]
                    ),
                )
            )
            db.commit()
    finally:
        engine.dispose()
    demo.private("initialized", "0008_proof_vault\n")


def start():
    initialize()
    demo.launch(
        "provisioner",
        [sys.executable, "-m", "services.orchestrator.server"],
        lambda: (
            (STATE / "control/provisioner.sock").exists()
            and "Trusted provisioner ready" in (STATE / "provisioner.log").read_text()
        ),
    )
    demo.launch(
        "signer",
        [
            sys.executable,
            ROOT / "scripts/run_signer.py",
            "--config",
            STATE / "signer.secrets.json",
            "--name",
            demo.SIGNER_NAME,
            "--compose-project",
            "nexus-m8-demo",
        ],
        lambda: (
            "Restricted evidence signer ready" in (STATE / "signer.log").read_text()
        ),
    )
    demo.launch(
        "api",
        [
            sys.executable,
            ROOT / "scripts/run_confined_api.py",
            "--port",
            str(API_PORT),
            "--name",
            demo.API_NAME,
            "--compose-project",
            "nexus-m8-demo",
        ],
        lambda: demo.http_ready(demo.API + "/ready"),
    )


def web():
    demo.run(["npm", "run", "build"], timeout=300)
    demo.launch(
        "web",
        [
            ROOT / "node_modules/.bin/next",
            "start",
            ROOT / "apps/web",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(WEB_PORT),
        ],
        lambda: demo.http_ready(demo.WEB + "/login"),
    )


def restart_provisioner():
    import signal
    import time

    item = demo.read("provisioner.process.json")
    if demo.process_identity(item["pid"]) == item["start"]:
        os.kill(item["pid"], signal.SIGTERM)
        for _ in range(200):
            if demo.process_identity(item["pid"]) != item["start"]:
                break
            time.sleep(0.2)
        else:
            raise ValueError("QA_PROVISIONER_STOP_UNVERIFIED")
    start()


def stop_services(names=("web", "api", "signer", "provisioner")):
    import signal
    import time

    for name in names:
        path = STATE / f"{name}.process.json"
        if not path.exists():
            continue
        item = demo.read(path.name)
        if demo.process_identity(item["pid"]) == item["start"]:
            os.kill(item["pid"], signal.SIGTERM)
            for _ in range(225):
                if demo.process_identity(item["pid"]) != item["start"]:
                    break
                time.sleep(0.2)
            else:
                raise ValueError("QA_GRACEFUL_STOP_UNVERIFIED")
        path.unlink()


def refresh_api():
    def require_idle():
        engine = create_engine(
            dotenv_values(STATE / "api.env")["NEXUS_DATABASE_URL"], hide_parameters=True
        )
        try:
            with engine.connect() as connection:
                active = connection.scalar(
                    text(
                        "SELECT count(*) FROM evaluations WHERE status IN "
                        "('PROVISIONING', 'RUNNING', 'FINALIZING')"
                    )
                )
                if active:
                    raise ValueError("QA_ACTIVE_EVALUATIONS; defer code refresh")
        finally:
            engine.dispose()

    require_idle()
    demo.run(
        [
            sys.executable,
            ROOT / "scripts/build_api_image.py",
            "--tag",
            f"nexus-{SCOPE}-qa-api:{SCOPE}",
        ],
        timeout=600,
    )
    demo.run(
        [
            sys.executable,
            ROOT / "scripts/build_signer_image.py",
            "--tag",
            f"nexus-{SCOPE}-qa-signer:{SCOPE}",
        ],
        timeout=180,
    )
    require_idle()
    stop_services(("api", "signer"))
    start()


def preservation():
    before = demo.read(baseline_name())
    demo_url = json.loads(
        (ROOT / ".runtime/proof-demo/database.secrets.json").read_bytes()
    )["admin_url"]
    after = {
        "normal": demo.normal_snapshot(),
        **(
            {"m9": m9_snapshot()}
            if PROFILE in {"resource", "timing", "center", "ui"}
            else {}
        ),
        **(
            {"m10": instance_snapshot("resource-assurance")}
            if PROFILE in {"timing", "center", "ui"}
            else {}
        ),
        **(
            {"m101": instance_snapshot("timing-mitigation")}
            if PROFILE in {"center", "ui"}
            else {}
        ),
        **({"m11": instance_snapshot("assurance-center")} if PROFILE == "ui" else {}),
        "m8": capture(demo_url),
        "m8_images": {
            name: (ROOT / ".runtime/proof-demo" / name).read_text()
            for name in before["m8_images"]
        },
    }
    result = {
        "normal_unchanged": before["normal"] == after["normal"],
        **({"m11_unchanged": before["m11"] == after["m11"]} if PROFILE == "ui" else {}),
        **(
            {"m101_unchanged": before["m101"] == after["m101"]}
            if PROFILE in {"center", "ui"}
            else {}
        ),
        **(
            {"m10_unchanged": before["m10"] == after["m10"]}
            if PROFILE in {"timing", "center", "ui"}
            else {}
        ),
        **(
            {"m9_unchanged": before["m9"] == after["m9"]}
            if PROFILE in {"resource", "timing", "center", "ui"}
            else {}
        ),
        "m8_data_unchanged": before["m8"] == after["m8"],
        "m8_configuration_unchanged": before["m8_images"] == after["m8_images"],
    }
    demo.private("preservation-results.json", result)
    print(json.dumps(result, indent=2))
    assert all(result.values()), "PRESERVATION_DIFFERENCE_REQUIRES_REVIEW"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "initialize",
            "start",
            "web",
            "restart-provisioner",
            "preservation",
            "refresh-api",
            "stop",
        ],
    )
    args = parser.parse_args()
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    select_instance()
    {
        "initialize": initialize,
        "start": start,
        "web": web,
        "restart-provisioner": restart_provisioner,
        "preservation": preservation,
        "refresh-api": refresh_api,
        "stop": stop_services,
    }[args.action]()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - suppress secret-bearing setup errors
        raise SystemExit("ASSURANCE_QA_FAILED:" + type(error).__name__) from None
