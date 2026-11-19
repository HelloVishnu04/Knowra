from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.audit import record_audit_event
from app.api.dependencies import (
    Principal,
    get_principal,
    require_workspace_admin,
)
from app.core.database import get_session
from app.models.audit import AuditEvent
from app.models.user import User, WorkspaceMember

router = APIRouter()
WorkspaceRole = Literal["owner", "administrator", "member", "viewer"]
PrincipalDependency = Annotated[Principal, Depends(get_principal)]
AdminDependency = Annotated[Principal, Depends(require_workspace_admin)]
SessionDependency = Annotated[Session, Depends(get_session)]


class AddMember(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: WorkspaceRole = "member"


class ChangeRole(BaseModel):
    role: WorkspaceRole


def membership_payload(member: WorkspaceMember, user: User) -> dict:
    return {
        "id": member.id,
        "user_id": user.id,
        "email": user.email,
        "role": member.role,
        "created_at": member.created_at,
    }


def workspace_membership(
    session: Session, workspace_id: str, membership_id: str
) -> WorkspaceMember:
    membership = session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.id == membership_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )
    if membership is None:
        raise HTTPException(404, "Workspace membership not found")
    return membership


def owner_count(session: Session, workspace_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == "owner",
            )
        )
        or 0
    )


def enforce_role_authority(
    principal: Principal, current_role: str | None, requested_role: str | None
) -> None:
    privileged = {"owner", "administrator"}
    if principal.role != "owner" and (
        current_role in privileged or requested_role in privileged
    ):
        raise HTTPException(403, "Only an owner can manage privileged roles")


@router.get("/workspaces/current/members")
def list_members(
    principal: PrincipalDependency, session: SessionDependency
) -> list[dict]:
    rows = session.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == principal.workspace_id)
        .order_by(User.email)
    ).all()
    return [membership_payload(member, user) for member, user in rows]


@router.post("/workspaces/current/members", status_code=201)
def add_member(
    body: AddMember, principal: AdminDependency, session: SessionDependency
) -> dict:
    enforce_role_authority(principal, None, body.role)
    email = body.email.strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        raise HTTPException(404, "User account not found")
    existing = session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == principal.workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if existing is not None:
        raise HTTPException(409, "User is already a workspace member")
    member = WorkspaceMember(
        workspace_id=principal.workspace_id,
        user_id=user.id,
        role=body.role,
    )
    session.add(member)
    session.flush()
    record_audit_event(
        session,
        principal,
        action="workspace.member_added",
        resource_type="workspace_membership",
        resource_id=str(member.id),
        details={"user_id": str(user.id), "role": body.role},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "User is already a workspace member") from exc
    session.refresh(member)
    return membership_payload(member, user)


@router.patch("/workspaces/current/members/{membership_id}")
def change_member_role(
    membership_id: str,
    body: ChangeRole,
    principal: AdminDependency,
    session: SessionDependency,
) -> dict:
    member = workspace_membership(session, principal.workspace_id, membership_id)
    current_role = str(member.role)
    enforce_role_authority(principal, current_role, body.role)
    if (
        current_role == "owner"
        and body.role != "owner"
        and owner_count(session, principal.workspace_id) <= 1
    ):
        raise HTTPException(409, "A workspace must retain at least one owner")
    previous_role = current_role
    member.role = body.role
    record_audit_event(
        session,
        principal,
        action="workspace.member_role_changed",
        resource_type="workspace_membership",
        resource_id=str(member.id),
        details={
            "user_id": str(member.user_id),
            "previous_role": previous_role,
            "role": body.role,
        },
    )
    session.commit()
    user = session.get(User, member.user_id)
    if user is None:  # pragma: no cover - protected by the foreign key
        raise HTTPException(404, "User account not found")
    return membership_payload(member, user)


@router.delete("/workspaces/current/members/{membership_id}", status_code=204)
def remove_member(
    membership_id: str,
    principal: AdminDependency,
    session: SessionDependency,
) -> Response:
    member = workspace_membership(session, principal.workspace_id, membership_id)
    current_role = str(member.role)
    enforce_role_authority(principal, current_role, None)
    if current_role == "owner" and owner_count(session, principal.workspace_id) <= 1:
        raise HTTPException(409, "A workspace must retain at least one owner")
    record_audit_event(
        session,
        principal,
        action="workspace.member_removed",
        resource_type="workspace_membership",
        resource_id=str(member.id),
        details={"user_id": str(member.user_id), "role": current_role},
    )
    session.delete(member)
    session.commit()
    return Response(status_code=204)


@router.get("/workspaces/current/audit-events")
def list_audit_events(
    principal: AdminDependency,
    session: SessionDependency,
    limit: int = 100,
) -> list[dict]:
    bounded_limit = min(max(limit, 1), 500)
    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.workspace_id == principal.workspace_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(bounded_limit)
    ).all()
    return [
        {
            "id": event.id,
            "actor_user_id": event.actor_user_id,
            "action": event.action,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "outcome": event.outcome,
            "details": event.details_json,
            "created_at": event.created_at,
        }
        for event in events
    ]
