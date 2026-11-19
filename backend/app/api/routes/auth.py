import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    Principal,
    require_authenticated_principal,
)
from app.core.config import settings
from app.core.database import get_session
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.user import (
    AuthenticationThrottle,
    Organization,
    RefreshCredential,
    User,
    UserSession,
    Workspace,
    WorkspaceMember,
)

router = APIRouter()
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(24))


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class Registration(Credentials):
    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("Password must contain at least one letter and one number")
        return value


def user_payload(user: User, workspace_id: str, role: str) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "workspace_id": workspace_id,
        "role": role,
    }


def utc_now() -> datetime:
    return datetime.now(UTC)


def refresh_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def throttle_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.strip().lower().encode()).hexdigest()
    return f"{kind}:{digest}"


def login_throttle_ids(email: str, request: Request) -> tuple[str, str]:
    client_ip = request.client.host if request.client else "unknown"
    return throttle_id("email", email), throttle_id("ip", client_ip)


def ensure_login_allowed(session: Session, identifiers: tuple[str, str]) -> None:
    now = utc_now()
    records = session.scalars(
        select(AuthenticationThrottle).where(AuthenticationThrottle.id.in_(identifiers))
    ).all()
    if any(
        record.locked_until is not None and not is_expired(record.locked_until, now)
        for record in records
    ):
        raise HTTPException(
            429,
            "Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(settings.AUTH_LOCKOUT_MINUTES * 60)},
        )


def record_login_failure(session: Session, identifiers: tuple[str, str]) -> bool:
    now = utc_now()
    locked = False
    for identifier in identifiers:
        record = session.get(AuthenticationThrottle, identifier)
        if record is None:
            record = AuthenticationThrottle(
                id=identifier,
                failure_count=0,
                window_started_at=now,
            )
            session.add(record)
        elif is_expired(
            record.window_started_at
            + timedelta(minutes=settings.AUTH_FAILURE_WINDOW_MINUTES),
            now,
        ):
            record.failure_count = 0
            record.window_started_at = now
            record.locked_until = None
        record.failure_count = int(record.failure_count) + 1
        if record.failure_count >= settings.AUTH_FAILURE_LIMIT:
            record.locked_until = now + timedelta(minutes=settings.AUTH_LOCKOUT_MINUTES)
            locked = True
    session.commit()
    return locked


def clear_login_failures(session: Session, identifiers: tuple[str, str]) -> None:
    session.execute(
        delete(AuthenticationThrottle).where(AuthenticationThrottle.id.in_(identifiers))
    )


def is_expired(value: datetime, now: datetime) -> bool:
    if value.tzinfo is None:
        return value <= now.replace(tzinfo=None)
    return value <= now


def create_login_session(
    session: Session, user: User, user_agent: str
) -> tuple[UserSession, str]:
    expires_at = utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    auth_session = UserSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        user_agent=user_agent[:500],
        expires_at=expires_at,
    )
    refresh_token = secrets.token_urlsafe(48)
    session.add(auth_session)
    session.add(
        RefreshCredential(
            id=str(uuid.uuid4()),
            session_id=auth_session.id,
            token_hash=refresh_hash(refresh_token),
            expires_at=expires_at,
        )
    )
    return auth_session, refresh_token


def set_auth_cookies(
    response: Response,
    user: User,
    auth_session: UserSession,
    refresh_token: str,
) -> str:
    token = create_access_token(str(user.id), str(auth_session.id))
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        "knowra_session",
        token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        "knowra_refresh",
        refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path=f"{settings.API_V1_STR}/auth",
    )
    response.set_cookie(
        "knowra_csrf",
        csrf_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=False,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return token


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("knowra_session", path="/")
    response.delete_cookie("knowra_refresh", path=f"{settings.API_V1_STR}/auth")
    response.delete_cookie("knowra_csrf", path="/")


@router.post("/register", status_code=201)
def register(
    payload: Registration,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    if not settings.REGISTRATION_ENABLED:
        raise HTTPException(403, "Account registration is disabled")
    if session.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(409, "An account with this email already exists")
    user = User(
        id=str(uuid.uuid4()),
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    organization = Organization(id=str(uuid.uuid4()), name=f"{payload.email} workspace")
    workspace = Workspace(
        id=str(uuid.uuid4()),
        organization_id=organization.id,
        name=f"{payload.email.split('@', 1)[0]}'s workspace",
    )
    session.add(user)
    session.add(organization)
    session.add(workspace)
    session.add(
        WorkspaceMember(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
        )
    )
    auth_session, refresh_token = create_login_session(
        session, user, request.headers.get("user-agent", "")
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "An account with this email already exists") from exc
    token = set_auth_cookies(response, user, auth_session, refresh_token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_payload(user, str(workspace.id), "owner"),
    }


@router.post("/login")
def login(
    payload: Credentials,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    identifiers = login_throttle_ids(payload.email, request)
    ensure_login_allowed(session, identifiers)
    user = session.scalar(select(User).where(User.email == payload.email))
    password_hash = (
        str(user.hashed_password) if user is not None else DUMMY_PASSWORD_HASH
    )
    password_valid = verify_password(payload.password, password_hash)
    if user is None or not password_valid:
        locked = record_login_failure(session, identifiers)
        if locked:
            raise HTTPException(
                429,
                "Too many sign-in attempts. Try again later.",
                headers={"Retry-After": str(settings.AUTH_LOCKOUT_MINUTES * 60)},
            )
        raise HTTPException(401, "Invalid email or password")
    clear_login_failures(session, identifiers)
    membership = session.scalar(
        select(WorkspaceMember)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at, WorkspaceMember.id)
    )
    if membership is None:
        raise HTTPException(403, "Account does not belong to a workspace")
    auth_session, refresh_token = create_login_session(
        session, user, request.headers.get("user-agent", "")
    )
    session.commit()
    token = set_auth_cookies(response, user, auth_session, refresh_token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_payload(
            user, str(membership.workspace_id), str(membership.role or "member")
        ),
    }


@router.get("/config")
def auth_config() -> dict:
    return {"registration_enabled": settings.REGISTRATION_ENABLED}


@router.get("/me")
def me(
    principal: Annotated[Principal, Depends(require_authenticated_principal)],
) -> dict:
    assert principal.user is not None
    return user_payload(principal.user, principal.workspace_id, principal.role)


@router.get("/sessions")
def list_sessions(
    principal: Annotated[Principal, Depends(require_authenticated_principal)],
    session: Annotated[Session, Depends(get_session)],
    access_token: Annotated[str | None, Cookie(alias="knowra_session")] = None,
) -> list[dict]:
    current_session_id = ""
    if access_token:
        try:
            current_session_id = str(decode_access_token(access_token).get("sid") or "")
        except ValueError:
            pass
    records = session.scalars(
        select(UserSession)
        .where(UserSession.user_id == principal.user_id)
        .order_by(UserSession.created_at.desc())
    ).all()
    return [
        {
            "id": record.id,
            "user_agent": record.user_agent,
            "created_at": record.created_at,
            "expires_at": record.expires_at,
            "revoked_at": record.revoked_at,
            "current": record.id == current_session_id,
        }
        for record in records
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: str,
    response: Response,
    principal: Annotated[Principal, Depends(require_authenticated_principal)],
    session: Annotated[Session, Depends(get_session)],
    access_token: Annotated[str | None, Cookie(alias="knowra_session")] = None,
) -> Response:
    record = session.scalar(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == principal.user_id,
        )
    )
    if record is None:
        raise HTTPException(404, "Login session not found")
    record.revoked_at = utc_now()
    session.commit()
    if access_token:
        try:
            if str(decode_access_token(access_token).get("sid") or "") == session_id:
                clear_auth_cookies(response)
        except ValueError:
            pass
    response.status_code = 204
    return response


@router.post("/refresh")
def refresh(
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    refresh_token: Annotated[str | None, Cookie(alias="knowra_refresh")] = None,
) -> dict:
    if not refresh_token:
        raise HTTPException(401, "Refresh credential is missing")
    credential = session.scalar(
        select(RefreshCredential).where(
            RefreshCredential.token_hash == refresh_hash(refresh_token)
        )
    )
    if credential is None:
        raise HTTPException(401, "Refresh credential is invalid")
    auth_session = session.get(UserSession, credential.session_id)
    now = utc_now()
    if auth_session is None:
        raise HTTPException(401, "Login session is no longer valid")
    if credential.used_at is not None:
        auth_session.revoked_at = now
        session.commit()
        raise HTTPException(401, "Refresh credential reuse detected")
    if (
        auth_session.revoked_at is not None
        or is_expired(auth_session.expires_at, now)
        or is_expired(credential.expires_at, now)
    ):
        raise HTTPException(401, "Login session is no longer valid")
    user = session.get(User, auth_session.user_id)
    if user is None:
        auth_session.revoked_at = now
        session.commit()
        raise HTTPException(401, "User account no longer exists")

    replacement_token = secrets.token_urlsafe(48)
    replacement = RefreshCredential(
        id=str(uuid.uuid4()),
        session_id=auth_session.id,
        token_hash=refresh_hash(replacement_token),
        expires_at=auth_session.expires_at,
    )
    credential.used_at = now
    credential.replaced_by_id = replacement.id
    session.add(replacement)
    session.commit()
    token = set_auth_cookies(response, user, auth_session, replacement_token)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    access_token: Annotated[str | None, Cookie(alias="knowra_session")] = None,
    refresh_token: Annotated[str | None, Cookie(alias="knowra_refresh")] = None,
) -> Response:
    if authorization and authorization.lower().startswith("bearer "):
        access_token = authorization[7:].strip()
    session_ids: set[str] = set()
    if access_token:
        try:
            session_id = str(decode_access_token(access_token).get("sid") or "")
            if session_id:
                session_ids.add(session_id)
        except ValueError:
            pass
    if refresh_token:
        credential = session.scalar(
            select(RefreshCredential).where(
                RefreshCredential.token_hash == refresh_hash(refresh_token)
            )
        )
        if credential is not None:
            session_ids.add(str(credential.session_id))
    if session_ids:
        now = utc_now()
        for auth_session in session.scalars(
            select(UserSession).where(UserSession.id.in_(session_ids))
        ):
            auth_session.revoked_at = now
        session.commit()
    clear_auth_cookies(response)
    response.status_code = 204
    return response
