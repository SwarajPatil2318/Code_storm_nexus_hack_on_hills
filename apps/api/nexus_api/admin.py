from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from nexus_api.access import AccessError
from nexus_api.auth import DB, Identity, audit, hasher, require_role
from nexus_api.events import EventType
from nexus_api.identity_schemas import Role, UserCreate, UserResponse, UserUpdate
from nexus_api.models import AuthSession, User

router = APIRouter(prefix="/admin", tags=["administration"])


@router.get("/users", response_model=list[UserResponse])
def users(request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, Role.ADMIN)
    return list(db.scalars(select(User).order_by(User.created_at).limit(200)))


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(body: UserCreate, request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, Role.ADMIN)
    user = User(
        email=body.email,
        display_name=body.display_name,
        role=body.role.value,
        password_hash=hasher.hash(body.password.get_secret_value()),
        is_demo=False,
    )
    db.add(user)
    audit(db, request, EventType.USER_CREATED, identity.user.id, "ADMIN_USER_CREATED")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AccessError(409, "user_exists", "A user with that email already exists") from None
    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: UUID, body: UserUpdate, request: Request, db: DB, identity: Identity):
    require_role(db, request, identity, Role.ADMIN)
    # Lock the same ordered set before changing any account to protect the final active admin.
    admins = list(
        db.scalars(
            select(User)
            .where(User.role == Role.ADMIN, User.is_active.is_(True))
            .order_by(User.id)
            .with_for_update()
        )
    )
    user = db.get(User, user_id)
    if user is None:
        raise AccessError(404, "not_found", "User not found")
    if (
        user in admins
        and len(admins) == 1
        and (body.is_active is False or (body.role is not None and body.role != Role.ADMIN))
    ):
        raise AccessError(409, "last_admin", "The final active administrator must be retained")
    if body.role is not None:
        user.role = body.role.value
    if body.is_active is not None:
        user.is_active = body.is_active
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    audit(db, request, EventType.USER_UPDATED, identity.user.id, "ADMIN_USER_UPDATED")
    db.commit()
    return user
