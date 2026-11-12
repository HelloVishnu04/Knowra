import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
from app.rag.documents import DocumentRetriever

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = REPO_ROOT / "datasets" / "eval" / "document_route_golden.jsonl"
DEFAULT_REPORTS = REPO_ROOT / "datasets" / "eval" / "reports"


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    if len(cases) < 15:
        raise ValueError("The document-route golden set must contain at least 15 cases")
    return cases


def reference_ids(kb_id: str, required_terms: list[str]) -> list[str]:
    lowered = [term.casefold() for term in required_terms]
    with SessionLocal() as session:
        rows = (
            session.query(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
            .filter(
                Document.status == "ready",
                KnowledgeBase.id == kb_id,
                KnowledgeBase.workspace_id == settings.LOCAL_WORKSPACE_ID,
            )
            .all()
        )
    return [
        row.id
        for row in rows
        if row.id
        and row.content
        and all(term in row.content.casefold() for term in lowered)
    ]


async def ragas_id_scores(
    retrieved_ids: list[str], relevant_ids: list[str]
) -> tuple[float, float]:
    try:
        from ragas import SingleTurnSample
        from ragas.metrics import IDBasedContextPrecision, IDBasedContextRecall
    except ImportError as exc:
        raise RuntimeError(
            "Install evaluation dependencies with `uv sync --extra eval`."
        ) from exc

    sample = SingleTurnSample(
        retrieved_context_ids=list[str | int](retrieved_ids),
        reference_context_ids=list[str | int](relevant_ids),
    )
    precision = await IDBasedContextPrecision().single_turn_ascore(sample)
    recall = await IDBasedContextRecall().single_turn_ascore(sample)
    return float(precision), float(recall)


async def evaluate_mode(
    cases: list[dict[str, Any]],
    *,
    kb_id: str,
    mode: str,
    top_k: int,
    use_ragas: bool,
) -> dict[str, Any]:
    retriever = DocumentRetriever()
    rows = []
    for case in cases:
        relevant = reference_ids(kb_id, case["required_terms"])
        if not relevant:
            raise ValueError(
                f"No indexed chunk contains the required terms for case {case['id']}. "
                "Upload datasets/eval/phase3_identifier_corpus.md to the selected KB."
            )
        result = await retriever.retrieve(
            case["question"],
            workspace_id=settings.LOCAL_WORKSPACE_ID,
            top_k=top_k,
            filters={
                "knowledge_base_id": kb_id,
                "retrieval_mode": "dense" if mode == "dense" else "hybrid",
                "rerank": mode == "hybrid_rerank",
            },
        )
        retrieved = [chunk.id for chunk in result.chunks]
        relevant_set = set(relevant)
        hit_ranks = [
            rank
            for rank, chunk_id in enumerate(retrieved, start=1)
            if chunk_id in relevant_set
        ]
        precision = len(hit_ranks) / len(retrieved) if retrieved else 0.0
        recall = len({item for item in retrieved if item in relevant_set}) / len(
            relevant
        )
        if use_ragas:
            precision, recall = await ragas_id_scores(retrieved, relevant)
        rows.append(
            {
                "id": case["id"],
                "question": case["question"],
                "retrieved_ids": retrieved,
                "reference_ids": relevant,
                "context_precision": precision,
                "context_recall": recall,
                "reciprocal_rank": 1.0 / min(hit_ranks) if hit_ranks else 0.0,
                "latency_ms": result.latency_ms,
            }
        )
    return {
        "mode": mode,
        "summary": {
            "context_precision": mean(row["context_precision"] for row in rows),
            "context_recall": mean(row["context_recall"] for row in rows),
            "mrr": mean(row["reciprocal_rank"] for row in rows),
            "mean_latency_ms": mean(row["latency_ms"] for row in rows),
            "case_count": len(rows),
        },
        "cases": rows,
    }


async def run(args: argparse.Namespace) -> Path:
    cases = load_cases(args.dataset)
    modes = ["dense", "hybrid", "hybrid_rerank"]
    reports = [
        await evaluate_mode(
            cases,
            kb_id=args.kb_id,
            mode=mode,
            top_k=args.top_k,
            use_ragas=not args.skip_ragas,
        )
        for mode in modes
    ]
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "knowledge_base_id": args.kb_id,
        "top_k": args.top_k,
        "embedding_model": settings.EMBEDDING_MODEL,
        "sparse_model": settings.SPARSE_MODEL,
        "reranker_model": settings.RERANKER_MODEL,
        "ragas_id_metrics": not args.skip_ragas,
        "results": reports,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = output_dir / f"document_retrieval_{stamp}.json"
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare dense, hybrid, and hybrid+reranker document retrieval."
    )
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--skip-ragas",
        action="store_true",
        help="Use equivalent local ID metrics without importing Ragas.",
    )
    args = parser.parse_args()
    if args.top_k < 1 or args.top_k > 20:
        parser.error("--top-k must be between 1 and 20")
    output = asyncio.run(run(args))
    print(output)


if __name__ == "__main__":
    main()
