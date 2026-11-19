import asyncio
import contextlib
from typing import Any

HEARTBEAT_SECONDS = 10
HEARTBEAT_TTL_SECONDS = 35
WORKER_KEYS = {
    "ingest": "knowra:health:worker:ingest",
    "sandbox": "knowra:health:worker:sandbox",
}


async def _heartbeat(ctx: dict[str, Any], worker: str) -> None:
    key = WORKER_KEYS[worker]
    while True:
        await ctx["redis"].set(key, "online", ex=HEARTBEAT_TTL_SECONDS)
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def start_worker_heartbeat(ctx: dict[str, Any], worker: str) -> None:
    task = asyncio.create_task(_heartbeat(ctx, worker), name=f"{worker}-heartbeat")
    ctx["worker_heartbeat_task"] = task
    await asyncio.sleep(0)


async def stop_worker_heartbeat(ctx: dict[str, Any], worker: str) -> None:
    task = ctx.pop("worker_heartbeat_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await ctx["redis"].delete(WORKER_KEYS[worker])
