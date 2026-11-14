import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from structlog.contextvars import bind_contextvars

from app.agents.checkpoint import open_checkpointer
from app.api.routes import auth, chat, execution, knowledge, repositories, runs
from app.core.config import settings
from app.core.logging import setup_logging

setup_logging()


@asynccontextmanager
async def lifespan(application: FastAPI):
    checkpointer, manager = await open_checkpointer()
    application.state.agent_checkpointer = checkpointer
    try:
        yield
    finally:
        if manager is not None:
            await manager.__aexit__(None, None, None)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)
app.state.agent_checkpointer = InMemorySaver()

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
app.include_router(runs.router, prefix=settings.API_V1_STR, tags=["runs"])
app.include_router(execution.router, prefix=settings.API_V1_STR, tags=["execution"])
app.include_router(
    repositories.router, prefix=settings.API_V1_STR, tags=["repositories"]
)
