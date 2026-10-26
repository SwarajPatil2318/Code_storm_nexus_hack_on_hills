"""Development-stage identity: opaque sessions, Argon2id, CSRF and database throttling."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from nexus_api.access import AccessError, database
from nexus_api.events import EventType
from nexus_api.identity_schemas import (
    CsrfResponse,
    DemoConfigResponse,
    DemoIdentity,
    LoginRequest,
    Role,
    SessionResponse,
    UserResponse,
)
from nexus_api.models import AuthAudit, AuthSession, LoginThrottle, User

router = APIRouter(prefix="/auth", tags=["identity"])
hasher = PasswordHasher()
# Unknown accounts incur the same expensive password verification as real accounts.
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
DB = Annotated[Session, Depends(database)]
DEMO_IDENTITIES = [
    DemoIdentity(email="red@nexus.local", display_name="Red Operator", role=Role.RED),
    DemoIdentity(email="blue@nexus.local", display_name="Blue Operator", role=Role.BLUE),
    DemoIdentity(email="auditor@nexus.local", display_name="Evidence Auditor", role=Role.AUDITOR),
    DemoIdentity(email="admin@nexus.local", display_name="Platform Administrator", role=Role.ADMIN),
]


def now() -> datetime:
    return datetime.now(UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(encoded: str, password: str) -> bool:
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def audit(
    db: Session, request: Request, event_type: EventType, actor_id=None, reason="APPLICATION_ACTION"
) -> None:
    db.add(
        AuthAudit(
            actor_id=actor_id,
            event_type=event_type.value,
            correlation_id=request.state.request_id,
            reason_code=reason,
        )
    )


def cookie_session(request: Request, db: Session) -> AuthSession | None:
    token = request.cookies.get(request.app.state.settings.session_cookie_name)
    if not token or len(token) > 128:
        return None
    return db.scalar(select(AuthSession).where(AuthSession.token_hash == digest(token)))


def valid_session(request: Request, db: Session) -> AuthSession:
    session = cookie_session(request, db)
    if session is None:
        raise AccessError(401, "unauthorized", "Authentication is required")
    if session.expires_at <= now():
        audit(db, request, EventType.AUTH_SESSION_EXPIRED, session.user_id, "SESSION_EXPIRED")
        db.delete(session)
        db.commit()
        raise AccessError(401, "session_expired", "Your session has expired. Please sign in again")
    return session


def check_csrf(request: Request, db: Session, session: AuthSession) -> None:
    settings = request.app.state.settings
    token = request.headers.get("X-CSRF-Token", "")
    origin = request.headers.get("Origin")
    if origin not in settings.cors_origins or not secrets.compare_digest(
        token.encode("utf-8"), session.csrf_token.encode("ascii")
    ):
        audit(db, request, EventType.ACCESS_DENIED, session.user_id, "CSRF_REJECTED")
        db.commit()
        raise AccessError(
            403, "csrf_rejected", "Request origin or CSRF token could not be verified"
        )


@dataclass
class Principal:
    user: User
    session: AuthSession


def principal(request: Request, db: DB) -> Principal:
    session = valid_session(request, db)
    user = db.get(User, session.user_id) if session.user_id else None
    settings = request.app.state.settings
    if (
        user is None
        or not user.is_active
        or (
            user.is_demo
            and (not settings.demo_auth_enabled or settings.environment == "production")
        )
    ):
        raise AccessError(401, "unauthorized", "Authentication is required")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_csrf(request, db, session)
    return Principal(user=user, session=session)


Identity = Annotated[Principal, Depends(principal)]


def deny(db: Session, request: Request, identity: Principal, code="forbidden", status=403) -> None:
    audit(db, request, EventType.ACCESS_DENIED, identity.user.id, "AUTHORIZATION_DENIED")
    db.commit()
    raise AccessError(status, code, "This operation is not permitted")


def require_role(db: Session, request: Request, identity: Principal, *roles: Role) -> None:
    if identity.user.role not in roles:
        deny(db, request, identity)


def issue_session(
    request: Request, response: Response, db: Session, user: User | None = None
) -> AuthSession:
    settings = request.app.state.settings
    raw = secrets.token_urlsafe(32)
    ttl = settings.session_ttl_seconds if user else 900
    session = AuthSession(
        token_hash=digest(raw),
        csrf_token=secrets.token_urlsafe(32),
        user_id=user.id if user else None,
        expires_at=now() + timedelta(seconds=ttl),
    )
    db.add(session)
    response.set_cookie(
        settings.session_cookie_name,
        raw,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=ttl,
        path="/",
    )
    return session


def session_response(identity: Principal) -> SessionResponse:
    return SessionResponse(
        user=UserResponse.model_validate(identity.user),
        expires_at=identity.session.expires_at,
        csrf_token=identity.session.csrf_token,
    )


@router.get("/csrf", response_model=CsrfResponse)
def csrf(request: Request, response: Response, db: DB):
    session = cookie_session(request, db)
    if session is None or session.expires_at <= now():
        if session is not None:
            db.delete(session)
        session = issue_session(request, response, db)
        db.commit()
    return CsrfResponse(csrf_token=session.csrf_token)


@router.get("/session", response_model=SessionResponse)
def get_session(identity: Identity):
    return session_response(identity)


@router.get("/demo", response_model=DemoConfigResponse)
def demo(request: Request):
    enabled = request.app.state.settings.demo_auth_enabled
    return DemoConfigResponse(enabled=enabled, identities=DEMO_IDENTITIES if enabled else [])


def throttle(request: Request, db: Session, email: str) -> str:
    settings = request.app.state.settings
    account_key = digest("account:" + email)
    peer_key = digest("peer:" + (request.client.host if request.client else "unknown"))
    expired = now() - timedelta(seconds=settings.login_window_seconds)
    blocked = False
    for key, limit in [
        (account_key, settings.login_attempt_limit),
        (peer_key, settings.login_peer_limit),
    ]:
        statement = insert(LoginThrottle).values(key=key, attempts=1, window_started_at=now())
        statement = statement.on_conflict_do_update(
            index_elements=[LoginThrottle.key],
            set_={
                "attempts": case(
                    (LoginThrottle.window_started_at <= expired, 1),
                    else_=LoginThrottle.attempts + 1,
                ),
                "window_started_at": case(
                    (LoginThrottle.window_started_at <= expired, now()),
                    else_=LoginThrottle.window_started_at,
                ),
            },
        ).returning(LoginThrottle.attempts)
        attempts = db.execute(statement).scalar_one()
        blocked = blocked or attempts > limit
    # Persist counters before doing expensive password hashing; shared across API workers.
    if blocked:
        audit(db, request, EventType.AUTH_THROTTLED, reason="LOGIN_THROTTLED")
    db.commit()
    if blocked:
        raise AccessError(429, "login_throttled", "Too many login attempts. Please try again later")
    return account_key


@router.post("/login", response_model=SessionResponse)
def login(body: LoginRequest, request: Request, response: Response, db: DB):
    old_session = valid_session(request, db)
    check_csrf(request, db, old_session)
    account_key = throttle(request, db, body.email)
    user = db.scalar(select(User).where(User.email == body.email))
    valid = verify_password(
        user.password_hash if user and user.password_hash else DUMMY_HASH,
        body.password.get_secret_value(),
    )
    settings = request.app.state.settings
    if (
        not valid
        or user is None
        or not user.is_active
        or (
            user.is_demo
            and (not settings.demo_auth_enabled or settings.environment == "production")
        )
    ):
        audit(db, request, EventType.AUTH_LOGIN_FAILED, reason="INVALID_CREDENTIALS")
        db.commit()
        raise AccessError(401, "invalid_credentials", "Email or password is incorrect")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(body.password.get_secret_value())
    # Password-verified switching always rotates the cookie and revokes the old identity.
    db.delete(old_session)
    session = issue_session(request, response, db, user)
    db.execute(delete(LoginThrottle).where(LoginThrottle.key == account_key))
    audit(db, request, EventType.AUTH_LOGIN_SUCCEEDED, user.id, "PASSWORD_VERIFIED")
    db.commit()
    return session_response(Principal(user=user, session=session))


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DB, identity: Identity):
    audit(db, request, EventType.AUTH_LOGOUT, identity.user.id, "SESSION_REVOKED")
    db.delete(identity.session)
    db.commit()
    settings = request.app.state.settings
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
