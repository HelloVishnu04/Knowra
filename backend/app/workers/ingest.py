import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import ClassVar

from arq.connections import RedisSettings
from qdrant_client import AsyncQdrantClient, models

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.knowledge import Document, DocumentChunk, DocumentVersion, KnowledgeBase
from app.rag.documents import embed
from app.storage.objects import object_store
from app.workers.code_ingest import ingest_repository

logger = logging.getLogger(__name__)


async def ensure_collection(client: AsyncQdrantClient, vector_size: int) -> None:
    if await client.collection_exists(settings.QDRANT_COLLECTION):
        return
    await client.create_collection(
        settings.QDRANT_COLLECTION,
        vectors_config={
            "dense": models.VectorParams(
                size=vector_size, distance=models.Distance.COSINE
            )
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)
        },
    )
    for field in (
        "workspace_id",
        "knowledge_base_id",
        "embedding_model",
        "sparse_model",
    ):
        await client.create_payload_index(
            settings.QDRANT_COLLECTION,
            field,
            models.PayloadSchemaType.KEYWORD,
        )


def parse_document(path: Path):
    from docling.datamodel.base_models import ConversionStatus
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(path)
    if result.status != ConversionStatus.SUCCESS:
        raise ValueError("Document conversion did not complete")
    return result.document


def chunk_document(document) -> list[dict]:
    from docling.chunking import HybridChunker

    chunker = HybridChunker(tokenizer=settings.CHUNK_TOKENIZER, max_tokens=384)
    chunks = []
    for chunk in chunker.chunk(dl_doc=document):
        text = chunker.contextualize(chunk=chunk).strip()
        if text:
            pages = sorted(
                {p.page_no for item in chunk.meta.doc_items for p in item.prov}
            )
            chunks.append(
                {
                    "content": text,
                    "metadata": {
                        "pages": pages,
                        "sections": list(chunk.meta.headings or []),
                    },
                }
            )
    if not chunks:
        raise ValueError("No readable content found in document")
    return chunks


def set_status(document_id: str, status: str, error: str | None = None):
    with SessionLocal.begin() as session:
        doc = session.get(Document, document_id)
        doc.status, doc.error = status, error


async def ingest_document(ctx, document_id: str):
    client = AsyncQdrantClient(url=settings.QDRANT_URL)
    try:
        with SessionLocal() as session:
            doc = session.get(Document, document_id)
            if doc is None or doc.status == "ready":
                return
            version = session.query(DocumentVersion).filter_by(document_id=doc.id).one()
            kb = session.get(KnowledgeBase, doc.knowledge_base_id)
            key, name, kb_id, workspace_id = (
                version.file_path,
                doc.name,
                kb.id,
                kb.workspace_id,
            )
        set_status(document_id, "parsing")
        data = await asyncio.to_thread(object_store().get, key)
        with tempfile.TemporaryDirectory(prefix="knowra-ingest-") as temp:
            path = Path(temp) / ("document" + Path(name).suffix.lower())
            await asyncio.to_thread(path.write_bytes, data)
            document = await asyncio.to_thread(parse_document, path)
            set_status(document_id, "chunking")
            parsed = await asyncio.to_thread(chunk_document, document)
        set_status(document_id, "embedding")
        with SessionLocal.begin() as session:
            session.query(DocumentChunk).filter_by(document_id=document_id).delete()
            for index, chunk in enumerate(parsed):
                chunk["id"] = str(uuid.uuid5(uuid.UUID(document_id), str(index)))
                session.add(
                    DocumentChunk(
                        id=chunk["id"],
                        document_id=document_id,
                        chunk_index=index,
                        content=chunk["content"],
                        metadata_json=chunk["metadata"],
                    )
                )
        for start in range(0, len(parsed), 16):
            batch = parsed[start : start + 16]
            vectors = await embed([chunk["content"] for chunk in batch])
            await ensure_collection(client, len(vectors[0]))
            await client.upsert(
                settings.QDRANT_COLLECTION,
                wait=True,
                points=[
                    models.PointStruct(
                        id=chunk["id"],
                        vector={
                            "dense": vector,
                            "sparse": models.Document(
                                text=chunk["content"], model=settings.SPARSE_MODEL
                            ),
                        },
                        payload={
                            "workspace_id": workspace_id,
                            "knowledge_base_id": kb_id,
                            "document_id": document_id,
                            "embedding_model": settings.EMBEDDING_MODEL,
                            "sparse_model": settings.SPARSE_MODEL,
                        },
                    )
                    for chunk, vector in zip(batch, vectors, strict=True)
                ],
            )
        set_status(document_id, "ready")
    except Exception:
        logger.exception("Document ingestion failed: %s", document_id)
        set_status(
            document_id,
            "failed",
            "Indexing failed. Check worker logs, model availability, and file validity; then retry.",
        )
        raise
    finally:
        await client.close()


class WorkerSettings:
    functions: ClassVar = [ingest_document, ingest_repository]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 1
    job_timeout = 1800
    max_tries = 1
