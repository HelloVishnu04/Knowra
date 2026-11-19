import asyncio
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_principal, require_workspace_writer
from app.core.config import settings
from app.core.database import get_session
from app.models.knowledge import Document, DocumentChunk, DocumentVersion, KnowledgeBase
from app.storage.objects import object_store

router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(get_principal)]
WriterDependency = Annotated[Principal, Depends(require_workspace_writer)]


class CreateKnowledgeBase(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    description: str = Field(default="", max_length=2000)


def require_kb(session: Session, kb_id: str, workspace_id: str):
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None or kb.workspace_id != workspace_id:
        raise HTTPException(404, "Knowledge base not found")
    return kb


def document_json(doc):
    return {"id": doc.id, "name": doc.name, "status": doc.status, "error": doc.error}


async def enqueue(document_id: str):
    pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    try:
        await pool.enqueue_job("ingest_document", document_id)
    finally:
        await pool.aclose()


@router.get("/knowledge-bases")
def list_kbs(session: SessionDependency, principal: PrincipalDependency):
    return [
        {"id": kb.id, "name": kb.name, "description": kb.description}
        for kb in session.query(KnowledgeBase)
        .filter_by(workspace_id=principal.workspace_id)
        .order_by(KnowledgeBase.created_at.desc())
        .all()
    ]


@router.post("/knowledge-bases", status_code=201)
def create_kb(
    body: CreateKnowledgeBase, session: SessionDependency, principal: WriterDependency
):
    kb = KnowledgeBase(
        name=body.name.strip(),
        description=body.description,
        workspace_id=principal.workspace_id,
    )
    session.add(kb)
    session.commit()
    return {"id": kb.id, "name": kb.name, "description": kb.description}


@router.get("/knowledge-bases/{kb_id}/documents")
def list_documents(
    kb_id: str, session: SessionDependency, principal: PrincipalDependency
):
    require_kb(session, kb_id, principal.workspace_id)
    return [
        document_json(d)
        for d in session.query(Document)
        .filter_by(knowledge_base_id=kb_id)
        .order_by(Document.created_at.desc())
        .all()
    ]


@router.post("/knowledge-bases/{kb_id}/documents", status_code=202)
async def upload(
    kb_id: str,
    file: UploadFile,
    session: SessionDependency,
    principal: WriterDependency,
):
    require_kb(session, kb_id, principal.workspace_id)
    name = (file.filename or "").replace("\\", "/").split("/")[-1]
    suffix = Path(name).suffix.lower()
    if suffix not in {".pdf", ".docx", ".pptx", ".xlsx"}:
        raise HTTPException(415, "Upload a PDF, DOCX, PPTX, or XLSX file")
    name = Path(name).stem[:200] + suffix
    data = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File exceeds the upload limit")
    if (
        not data
        or (suffix == ".pdf" and not data.startswith(b"%PDF-"))
        or (suffix != ".pdf" and not data.startswith(b"PK"))
    ):
        raise HTTPException(422, "File contents do not match the document type")
    document_id = str(uuid4())
    key = f"{principal.workspace_id}/{document_id}/original{suffix}"
    store = object_store()
    await asyncio.to_thread(store.put, key, data)
    doc = Document(
        id=document_id, knowledge_base_id=kb_id, name=name[:255], status="pending"
    )
    try:
        session.add(doc)
        session.add(DocumentVersion(document_id=document_id, version=1, file_path=key))
        session.commit()
    except Exception:
        session.rollback()
        await asyncio.to_thread(store.delete, key)
        raise
    try:
        await enqueue(document_id)
    except Exception:  # noqa: BLE001 - queue failures are persisted for retry
        doc.status, doc.error = (
            "failed",
            "Queue unavailable. Start Redis and retry indexing.",
        )
        session.commit()
    return document_json(doc)


@router.post("/knowledge-bases/{kb_id}/documents/{document_id}/retry", status_code=202)
async def retry(
    kb_id: str,
    document_id: str,
    session: SessionDependency,
    principal: WriterDependency,
):
    require_kb(session, kb_id, principal.workspace_id)
    updated = (
        session.query(Document)
        .filter_by(id=document_id, knowledge_base_id=kb_id, status="failed")
        .update({"status": "pending", "error": None})
    )
    if not updated:
        raise HTTPException(409, "Only failed documents can be retried")
    session.commit()
    doc = session.get(Document, document_id)
    try:
        await enqueue(document_id)
    except Exception:  # noqa: BLE001 - queue failures are persisted for retry
        doc.status, doc.error = (
            "failed",
            "Queue unavailable. Start Redis and retry indexing.",
        )
        session.commit()
    return document_json(doc)


@router.get("/chunks/{chunk_id}")
def get_chunk(
    chunk_id: str, session: SessionDependency, principal: PrincipalDependency
):
    row = (
        session.query(DocumentChunk, Document)
        .join(Document)
        .join(KnowledgeBase)
        .filter(
            DocumentChunk.id == chunk_id,
            Document.status == "ready",
            KnowledgeBase.workspace_id == principal.workspace_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(404, "Chunk not found")
    chunk, doc = row
    return {
        "id": chunk.id,
        "content": chunk.content,
        "document_name": doc.name,
        "metadata": chunk.metadata_json,
    }
