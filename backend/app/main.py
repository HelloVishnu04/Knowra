from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uuid
from structlog.contextvars import bind_contextvars

from app.core.config import settings
from app.core.logging import setup_logging
from app.api.routes import auth, chat, knowledge

setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def structlog_middleware(request, call_next):
    run_id = str(uuid.uuid4())
    bind_contextvars(run_id=run_id, method=request.method, path=request.url.path)
    response = await call_next(request)
    return response

@app.get("/health")
async def health_check():
    return {"status": "ok"}

app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(chat.router, prefix=f"{settings.API_V1_STR}/chat", tags=["chat"])
app.include_router(knowledge.router, prefix=settings.API_V1_STR, tags=["knowledge"])
