import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List
from structlog.contextvars import get_contextvars
import structlog

from app.llm.gateway import gateway

logger = structlog.get_logger(__name__)

router = APIRouter()

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    model: str = "qwen:7b" # Default fallback for ollama
    provider: str = "ollama"
    stream: bool = True

@router.post("")
async def chat(request: ChatRequest):
    run_id = get_contextvars().get("run_id", "unknown")
    logger.info("chat_request", model=request.model, provider=request.provider, stream=request.stream)
    
    provider = gateway.get_provider(request.provider)
    messages_dict = [{"role": msg.role, "content": msg.content} for msg in request.messages]

    if request.stream:
        async def event_generator():
            try:
                async for token in provider.stream_chat(messages_dict, request.model):
                    # SSE format
                    data = {"content": token, "run_id": run_id}
                    yield f"data: {json.dumps(data)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error("stream_generator_error", error=str(e))
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        
        return StreamingResponse(event_generator(), media_type="text/event-stream")
    else:
        content = await provider.chat(messages_dict, request.model)
        return {"content": content, "run_id": run_id}
