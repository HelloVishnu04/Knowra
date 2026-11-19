from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_session
from app.core.security import decode_access_token
from app.models.user import User, UserSession, WorkspaceMember

WorkspaceRole = Literal["owner", "administrator", "member", "viewer"]
WRITE_ROLES: set[str] = {"owner", "administrator", "member"}
ADMIN_ROLES: set[str] = {"owner", "administrator"}


@dataclass(frozen=True)
class Principal:
    user: User | None
    workspace_id: str
    role: WorkspaceRole

    @property
    def user_id(self) -> str | None:
        return str(self.user.id) if self.user is not None else None


def get_current_user(
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    knowra_session: Annotated[str | None, Cookie()] = None,
) -> User | None:
    token = knowra_session
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        if settings.AUTH_REQUIRED:
            raise HTTPException(401, "Authentication required")
        return None
    try:
        claims = decode_access_token(token)
        user_id = str(claims["sub"])
        session_id = str(claims.get("sid") or "")
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    if not session_id:
        raise HTTPException(401, "Login session is no longer valid")
    auth_session = session.scalar(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(UTC),
        )
    )
    if auth_session is None:
        raise HTTPException(401, "Login session is no longer valid")
    user = session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(401, "User account no longer exists")
    return user


def require_user(user: Annotated[User | None, Depends(get_current_user)]) -> User:
    if user is None:
        raise HTTPException(401, "Authentication required")
    return user


def get_principal(
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User | None, Depends(get_current_user)],
    workspace_header: Annotated[str | None, Header(alias="X-Workspace-ID")] = None,
) -> Principal:
    """Resolve workspace scope from membership, never from an untrusted ID alone."""
    if user is None:
        if workspace_header and workspace_header != settings.LOCAL_WORKSPACE_ID:
            raise HTTPException(403, "Workspace access denied")
        return Principal(None, settings.LOCAL_WORKSPACE_ID, "owner")

    query = select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
    if workspace_header:
        query = query.where(WorkspaceMember.workspace_id == workspace_header)
    membership = session.scalar(
        query.order_by(WorkspaceMember.created_at, WorkspaceMember.id)
    )
    if membership is None:
        raise HTTPException(403, "Workspace access denied")
    role = str(membership.role or "member")
    if role not in {"owner", "administrator", "member", "viewer"}:
        raise HTTPException(403, "Workspace role is invalid")
    return Principal(user, str(membership.workspace_id), role)  # type: ignore[arg-type]


def require_workspace_writer(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    if principal.role not in WRITE_ROLES:
        raise HTTPException(403, "This workspace role is read-only")
    return principal


def require_authenticated_principal(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    if principal.user is None:
        raise HTTPException(401, "Authentication required")
    return principal


def require_workspace_admin(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    if principal.role not in ADMIN_ROLES:
        raise HTTPException(403, "Workspace administration permission is required")
    return principal
