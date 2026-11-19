from typing import Any

from sqlalchemy.orm import Session

from app.api.dependencies import Principal
from app.models.audit import AuditEvent


def record_audit_event(
    session: Session,
    principal: Principal,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        details_json=details or {},
    )
    session.add(event)
    return event
