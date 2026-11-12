import argparse
import asyncio

from qdrant_client import AsyncQdrantClient, models

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
from app.rag.documents import embed
from app.workers.ingest import ensure_collection


async def reindex(batch_size: int = 16) -> int:
    with SessionLocal() as session:
        rows = (
            session.query(DocumentChunk, Document, KnowledgeBase)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
            .filter(Document.status == "ready")
            .order_by(DocumentChunk.id)
            .all()
        )
    if not rows:
        return 0

    client = AsyncQdrantClient(url=settings.QDRANT_URL)
    try:
        indexed = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            vectors = await embed([chunk.content for chunk, _, _ in batch])
            await ensure_collection(client, len(vectors[0]))
            await client.upsert(
                settings.QDRANT_COLLECTION,
                wait=True,
                points=[
                    models.PointStruct(
                        id=chunk.id,
                        vector={
                            "dense": vector,
                            "sparse": models.Document(
                                text=chunk.content, model=settings.SPARSE_MODEL
                            ),
                        },
                        payload={
                            "workspace_id": kb.workspace_id,
                            "knowledge_base_id": kb.id,
                            "document_id": doc.id,
                            "embedding_model": settings.EMBEDDING_MODEL,
                            "sparse_model": settings.SPARSE_MODEL,
                        },
                    )
                    for (chunk, doc, kb), vector in zip(batch, vectors, strict=True)
                ],
            )
            indexed += len(batch)
        return indexed
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-index every ready SQL chunk into the Phase 3 Qdrant collection."
    )
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 100:
        parser.error("--batch-size must be between 1 and 100")
    count = asyncio.run(reindex(args.batch_size))
    print(f"Indexed {count} chunks into {settings.QDRANT_COLLECTION}")


if __name__ == "__main__":
    main()
