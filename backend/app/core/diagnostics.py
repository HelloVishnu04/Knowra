import asyncio
import importlib.util
from collections.abc import Awaitable, Callable
from importlib.metadata import PackageNotFoundError, version
from time import monotonic
from typing import Any

import httpx
import redis.asyncio as redis
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.worker_health import WORKER_KEYS

Check = Callable[[], Awaitable[None]]


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


async def _database() -> None:
    def query() -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    await asyncio.to_thread(query)


async def _redis() -> None:
    client = redis.from_url(settings.REDIS_URL)
    try:
        if not await client.ping():
            raise RuntimeError("Redis did not acknowledge the health check")
    finally:
        await client.aclose()


async def _qdrant() -> None:
    async with httpx.AsyncClient(timeout=settings.DIAGNOSTIC_TIMEOUT_SECONDS) as client:
        response = await client.get(f"{settings.QDRANT_URL.rstrip('/')}/readyz")
        response.raise_for_status()


async def _run_check(
    name: str, required: bool, check: Check
) -> tuple[str, dict[str, Any]]:
    started = monotonic()
    try:
        await asyncio.wait_for(check(), timeout=settings.DIAGNOSTIC_TIMEOUT_SECONDS)
        status, error = "available", None
    except Exception as exc:  # noqa: BLE001 - diagnostics must report every dependency
        status, error = "unavailable", type(exc).__name__
    return name, {
        "status": status,
        "required": required,
        "latency_ms": int((monotonic() - started) * 1000),
        "error": error,
    }


async def _worker_components() -> dict[str, dict[str, Any]]:
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        values = await client.mget(*WORKER_KEYS.values())
    except Exception as exc:  # noqa: BLE001 - Redis failure is reported elsewhere too
        return {
            f"worker_{name}": {
                "status": "unknown",
                "required": False,
                "error": type(exc).__name__,
            }
            for name in WORKER_KEYS
        }
    finally:
        await client.aclose()
    return {
        f"worker_{name}": {
            "status": "available" if value == "online" else "unavailable",
            "required": False,
            "error": None if value == "online" else "heartbeat_missing",
        }
        for (name, _), value in zip(WORKER_KEYS.items(), values, strict=True)
    }


async def component_status(
    *, include_workers: bool = True
) -> dict[str, dict[str, Any]]:
    results = await asyncio.gather(
        _run_check("database", True, _database),
        _run_check("redis", True, _redis),
        _run_check("qdrant", False, _qdrant),
    )
    components = dict(results)
    if include_workers:
        components.update(await _worker_components())
    return components


def feature_status() -> dict[str, dict[str, Any]]:
    docling = importlib.util.find_spec("docling") is not None
    fastembed = importlib.util.find_spec("fastembed") is not None
    return {
        "repository_browsing": {
            "status": "available",
            "reason": "does_not_require_a_model",
        },
        "code_parsing": {
            "status": "available",
            "tree_sitter": _package_version("tree-sitter"),
            "language_pack": _package_version("tree-sitter-language-pack"),
        },
        "document_conversion": {
            "status": "available" if docling else "unavailable",
            "reason": None if docling else "docling_not_installed",
        },
        "chat": {
            "status": "configuration_required",
            "reason": "configure_and_test_a_provider",
        },
        "embeddings": {
            "status": "configuration_required",
            "model": settings.EMBEDDING_MODEL,
            "reason": "embedding_service_must_be_configured",
        },
        "reranking": {
            "status": (
                "available"
                if settings.RERANKER_ENABLED and fastembed
                else "disabled"
                if not settings.RERANKER_ENABLED
                else "unavailable"
            ),
            "reason": (
                None
                if settings.RERANKER_ENABLED and fastembed
                else "disabled_by_configuration"
                if not settings.RERANKER_ENABLED
                else "fastembed_not_installed"
            ),
        },
        "sandbox_execution": {
            "status": "enabled" if settings.SANDBOX_EXECUTION_ENABLED else "disabled",
            "reason": (
                None
                if settings.SANDBOX_EXECUTION_ENABLED
                else "disabled_by_configuration"
            ),
        },
        "web_retrieval": {
            "status": "available" if settings.WEB_RETRIEVAL_ENABLED else "disabled",
            "provider": settings.WEB_SEARCH_PROVIDER,
            "reason": (
                None if settings.WEB_RETRIEVAL_ENABLED else "disabled_by_configuration"
            ),
        },
    }


def overall_status(components: dict[str, dict[str, Any]]) -> str:
    if any(
        item["required"] and item["status"] != "available"
        for item in components.values()
    ):
        return "unready"
    if any(item["status"] != "available" for item in components.values()):
        return "degraded"
    return "ready"
