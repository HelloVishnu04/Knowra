from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import Principal, get_principal, require_workspace_writer
from app.core.config import settings
from app.sandbox.queue import (
    create_execution_job,
    enqueue_execution_job,
    execution_job,
)

router = APIRouter()
PrincipalDependency = Annotated[Principal, Depends(get_principal)]
WriterDependency = Annotated[Principal, Depends(require_workspace_writer)]


class RunCodeRequest(BaseModel):
    language: Literal["python", "javascript"]
    code: str = Field(min_length=1, max_length=200_000)


@router.post("/execution/run", status_code=202)
async def run_code(
    body: RunCodeRequest, principal: WriterDependency
) -> dict[str, object]:
    if not settings.SANDBOX_EXECUTION_ENABLED:
        raise HTTPException(503, "Sandbox execution is disabled")
    filename = "main.py" if body.language == "python" else "main.js"
    command = "python main.py" if body.language == "python" else "node main.js"
    job = create_execution_job(
        workspace_id=principal.workspace_id,
        agent_run_id=None,
        repository_id=None,
        attempt=1,
        stage="run_code",
        command=command,
        files={filename: body.code},
    )
    try:
        await enqueue_execution_job(job.id)
    except Exception as exc:
        raise HTTPException(503, "Sandbox queue is unavailable") from exc
    return {"id": job.id, "status": job.status}


@router.get("/execution/{job_id}")
def get_execution(job_id: str, principal: PrincipalDependency) -> dict[str, object]:
    result = execution_job(job_id)
    if result is None or result["workspace_id"] != principal.workspace_id:
        raise HTTPException(404, "Execution job not found")
    return result
