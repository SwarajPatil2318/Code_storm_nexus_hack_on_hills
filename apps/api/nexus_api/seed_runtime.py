"""Explicit development fixtures: versions only, never synthetic evaluations or decisions."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.config import get_settings
from nexus_api.database import make_engine
from nexus_api.models import Artifact, ArtifactVersion, User, VersionGrant
from nexus_api.versioning import canonical, new_version


def main():
    settings = get_settings()
    if settings.environment != "development" or not settings.demo_auth_enabled:
        raise SystemExit("Initial runtime fixtures require development demo authentication")
    engine = make_engine(settings)
    with Session(engine) as db:
        users = [
            db.scalar(
                select(User).where(
                    User.email == email,
                    User.is_demo.is_(True),
                    User.is_active.is_(True),
                    User.role == role,
                )
            )
            for email, role in [
                ("red@nexus.local", "RED_OPERATOR"),
                ("blue@nexus.local", "BLUE_OPERATOR"),
            ]
        ]
        if not all(users):
            raise SystemExit("Provision the demo identities first")
        versions = []
        for user, kind, content in [
            (
                users[0],
                "attack",
                {
                    "cases": [
                        {"prompt": "A harmless local development request", "route": "mediated"},
                        {"prompt": "Synthetic forbidden Blue route probe", "route": "direct_blue"},
                        {
                            "prompt": "Synthetic forbidden model route probe",
                            "route": "direct_model",
                        },
                    ]
                },
            ),
            (users[1], "defence", {"blocked_terms": ["CANARY_PRIVATE"], "block_input": False}),
        ]:
            name = "Initial local " + kind + " v1"
            artifact = db.scalar(
                select(Artifact).where(Artifact.name == name, Artifact.owner_id == user.id)
            )
            if artifact is None:
                artifact = Artifact(
                    owner_id=user.id,
                    kind=kind,
                    name=name,
                    private_content=canonical(content).decode(),
                )
                db.add(artifact)
                db.flush()
            version = db.scalar(
                select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id)
            )
            versions.append(version or new_version(db, user.id, kind, content, artifact.id))
        if not db.get(VersionGrant, (versions[1].id, users[0].id)):
            db.add(VersionGrant(version_id=versions[1].id, red_id=users[0].id))
        db.commit()
    engine.dispose()
    print("Initial Red/Blue immutable versions provisioned; no evaluations executed")


if __name__ == "__main__":
    main()
