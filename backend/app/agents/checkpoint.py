from contextlib import AbstractAsyncContextManager
from typing import Any

import structlog
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import settings

logger = structlog.get_logger(__name__)


async def open_checkpointer() -> tuple[Any, AbstractAsyncContextManager[Any] | None]:
    """Open the configured saver, retaining an in-memory fallback for host dev."""
    if settings.LANGGRAPH_CHECKPOINTER == "memory":
        return InMemorySaver(), None
    if settings.LANGGRAPH_CHECKPOINTER != "redis":
        raise ValueError("LANGGRAPH_CHECKPOINTER must be redis or memory")
    manager: AbstractAsyncContextManager[Any] | None = None
    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        manager = AsyncRedisSaver.from_conn_string(settings.REDIS_URL)
        saver = await manager.__aenter__()
        await saver.asetup()
        logger.info("langgraph_checkpointer_ready", backend="redis")
        return saver, manager
    except Exception as exc:  # noqa: BLE001 - startup must retain the safe fallback
        if manager is not None:
            await manager.__aexit__(type(exc), exc, exc.__traceback__)
        logger.warning(
            "langgraph_checkpointer_fallback",
            backend="memory",
            error=str(exc),
        )
        return InMemorySaver(), None
