from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.graph import AgentOrchestrator
from app.agents.traces import AgentTraceStore
from app.api.dependencies import Principal, get_principal, require_workspace_writer
from app.code.patches import (
    PatchError,
    apply_patch_in_memory,
    extract_unified_diff,
    parse_unified_diff,
)
from app.code.workspace import CodeWorkspace
from app.core.database import get_session
from app.llm.gateway import gateway

router = APIRouter()
PrincipalDependency = Annotated[Principal, Depends(get_principal)]
WriterDependency = Annotated[Principal, Depends(require_workspace_writer)]


class ApprovalDecision(BaseModel):
    approved: bool | None = None
    action: Literal["approve", "edit", "reject"] | None = None
    patch: str | None = None


@router.get("/runs")
def list_runs(principal: PrincipalDependency, limit: int = 50) -> list[dict[str, Any]]:
    return AgentTraceStore().list_runs(workspace_id=principal.workspace_id, limit=limit)


@router.get("/runs/{run_id}")
def get_run(run_id: str, principal: PrincipalDependency) -> dict[str, Any]:
    result = AgentTraceStore().get_run(run_id, workspace_id=principal.workspace_id)
    if result is None:
        raise HTTPException(404, "Run not found")
    return result


@router.post("/runs/{run_id}/approval")
async def decide_run(
    run_id: str,
    decision: ApprovalDecision,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    principal: WriterDependency,
) -> dict[str, Any]:
    store = AgentTraceStore()
    current = store.get_run(run_id, workspace_id=principal.workspace_id)
    if current is None:
        raise HTTPException(404, "Run not found")
    if current["status"] != "pending_approval":
        raise HTTPException(409, "Run is not waiting for approval")
    action = decision.action or ("approve" if decision.approved else "reject")
    if action == "edit":
        if not decision.patch:
            raise HTTPException(422, "An edited patch is required")
        try:
            patch_set = parse_unified_diff(extract_unified_diff(decision.patch))
            patch_calls = [
                item for item in current["tool_calls"] if item["name"] == "create_patch"
            ]
            if not patch_calls:
                raise PatchError("This run does not contain a patch approval")
            repository_id = str(patch_calls[-1]["arguments"]["repository_id"])
            repository = CodeWorkspace().repository(
                repository_id, principal.workspace_id
            )
            apply_patch_in_memory(Path(repository.root_path), patch_set)
        except (PatchError, ValueError) as exc:
            raise HTTPException(422, f"Edited patch is invalid: {exc}") from exc
    try:
        if principal.user is not None and current["provider"] != "ollama":
            provider, _ = gateway.get_configured_provider(
                session,
                current["provider"],
                str(principal.user.id),
                principal.workspace_id,
            )
        else:
            provider = gateway.get_provider(current["provider"])
        orchestrator = AgentOrchestrator(
            provider=provider,
            checkpointer=request.app.state.agent_checkpointer,
            trace_store=store,
        )
        await orchestrator.resume(
            run_id,
            decision={"action": action, "patch": decision.patch},
        )
    except Exception as exc:
        raise HTTPException(503, "The saved agent run could not be resumed") from exc
    result = store.get_run(run_id, workspace_id=principal.workspace_id)
    if result is None:  # pragma: no cover
        raise HTTPException(404, "Run not found")
    return result
