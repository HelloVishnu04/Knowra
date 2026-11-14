import asyncio
import json
import uuid
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from structlog.contextvars import get_contextvars

from app.agents.graph import AgentOrchestrator
from app.core.config import settings
from app.llm.gateway import gateway

logger = structlog.get_logger(__name__)
router = APIRouter()


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    model: str = "qwen:0.5b"
    provider: str = "ollama"
    stream: bool = True
    knowledge_base_id: str | None = None
    repository_id: str | None = None
    conversation_id: str | None = None
    route: Literal["auto", "direct", "document", "web", "sql", "code", "multi"] = "auto"


@router.post("")
async def chat(request_body: ChatRequest, request: Request):
    run_id = str(get_contextvars().get("run_id") or uuid.uuid4())
    logger.info(
        "chat_request",
        model=request_body.model,
        provider=request_body.provider,
        stream=request_body.stream,
        requested_route=request_body.route,
    )
    try:
        provider = gateway.get_provider(request_body.provider)
    except ValueError as exc:
        raise HTTPException(400, "Unknown provider") from exc

    messages = [message.model_dump() for message in request_body.messages]
    queue: asyncio.Queue[dict[str, Any]] | None = (
        asyncio.Queue() if request_body.stream else None
    )
    orchestrator = AgentOrchestrator(
        provider=provider,
        checkpointer=request.app.state.agent_checkpointer,
        token_sink=queue,
    )
    try:
        state = orchestrator.initial_state(
            run_id=run_id,
            workspace_id=settings.LOCAL_WORKSPACE_ID,
            messages=messages,
            provider=request_body.provider,
            model=request_body.model,
            knowledge_base_id=request_body.knowledge_base_id,
            repository_id=request_body.repository_id,
            requested_route=request_body.route,
            conversation_id=request_body.conversation_id,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    if request_body.stream:

        async def event_generator():
            try:
                async for event in orchestrator.stream(state):
                    if event.get("error"):
                        logger.error("agent_stream_failed", error=event["error"])
                        yield (
                            "event: error\ndata: "
                            + json.dumps(
                                {"error": "Generation failed. Check the run trace."}
                            )
                            + "\n\n"
                        )
                        return
                    yield f"data: {json.dumps(event)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:
                logger.exception("stream_generator_error", error=str(exc))
                yield (
                    "event: error\ndata: "
                    + json.dumps({"error": "Generation failed. Check the run trace."})
                    + "\n\n"
                )

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    try:
        result = await orchestrator.run(state)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        logger.exception("agent_run_failed")
        raise HTTPException(503, "Agent execution is unavailable") from exc
    return {
        "content": result.get("answer", ""),
        "run_id": run_id,
        "route": result.get("route", "direct"),
        "status": (
            "pending_approval"
            if result.get("pending_tool_call")
            and result.get("approval_status") == "pending"
            else "completed"
        ),
        "citations": result.get("citations", []),
    }
