from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.agents.graph import AgentOrchestrator
from app.agents.traces import AgentTraceStore
from app.code.patches import (
    PatchError,
    apply_patch_in_memory,
    extract_unified_diff,
    parse_unified_diff,
)
from app.code.workspace import CodeWorkspace
from app.core.config import settings
from app.llm.gateway import gateway

router = APIRouter()


class ApprovalDecision(BaseModel):
    approved: bool | None = None
    action: Literal["approve", "edit", "reject"] | None = None
    patch: str | None = None


@router.get("/runs")
def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    return AgentTraceStore().list_runs(
        workspace_id=settings.LOCAL_WORKSPACE_ID, limit=limit
    )


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    result = AgentTraceStore().get_run(run_id, workspace_id=settings.LOCAL_WORKSPACE_ID)
    if result is None:
        raise HTTPException(404, "Run not found")
    return result


@router.post("/runs/{run_id}/approval")
async def decide_run(
    run_id: str, decision: ApprovalDecision, request: Request
) -> dict[str, Any]:
    store = AgentTraceStore()
    current = store.get_run(run_id, workspace_id=settings.LOCAL_WORKSPACE_ID)
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
                repository_id, settings.LOCAL_WORKSPACE_ID
            )
            apply_patch_in_memory(Path(repository.root_path), patch_set)
        except (PatchError, ValueError) as exc:
            raise HTTPException(422, f"Edited patch is invalid: {exc}") from exc
    try:
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
    result = store.get_run(run_id, workspace_id=settings.LOCAL_WORKSPACE_ID)
    if result is None:  # pragma: no cover
        raise HTTPException(404, "Run not found")
    return result
