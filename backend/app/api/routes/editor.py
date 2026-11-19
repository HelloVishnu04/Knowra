from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import Principal, get_principal, require_workspace_writer
from app.code.editor import EditorError, EditorService

router = APIRouter(prefix="/editor-workspaces", tags=["editor"])
Reader = Annotated[Principal, Depends(get_principal)]
Writer = Annotated[Principal, Depends(require_workspace_writer)]


class CreateWorkspace(BaseModel):
    repository_id: str = Field(min_length=1, max_length=100)


class SaveFile(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    content: str = Field(max_length=1024 * 1024)
    expected_version: str | None = Field(pattern=r"^[a-f0-9]{64}$")


def invoke(operation):
    try:
        return operation()
    except EditorError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("")
def list_workspaces(principal: Reader, repository_id: str):
    items = invoke(lambda: EditorService().list(principal, repository_id))
    return [{**item, "can_edit": principal.role != "viewer"} for item in items]


@router.post("", status_code=201)
def create_workspace(body: CreateWorkspace, principal: Writer):
    item = invoke(lambda: EditorService().create(principal, body.repository_id))
    return {**item, "can_edit": True}


@router.get("/{workspace_id}/tree")
def tree(
    workspace_id: str,
    principal: Reader,
    directory: str = "",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    hidden: bool = False,
):
    return invoke(
        lambda: EditorService().tree(
            workspace_id, principal, directory, offset, limit, hidden
        )
    )


@router.get("/{workspace_id}/file")
def read_file(
    workspace_id: str,
    principal: Reader,
    path: str = Query(min_length=1, max_length=1000),
):
    return invoke(lambda: EditorService().read(workspace_id, principal, path))


@router.put("/{workspace_id}/file")
def save_file(workspace_id: str, body: SaveFile, principal: Writer):
    return invoke(
        lambda: EditorService().write(
            workspace_id, principal, body.path, body.content, body.expected_version
        )
    )
