import hmac
import re
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.memory import InMemorySaver
from starlette.exceptions import HTTPException as StarletteHTTPException
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.agents.checkpoint import open_checkpointer
from app.api.dependencies import get_principal, require_user
from app.api.routes import (
    auth,
    chat,
    editor,
    execution,
    knowledge,
    providers,
    repositories,
    runs,
    workspaces,
)
from app.core.config import settings
from app.core.diagnostics import component_status, feature_status, overall_status
from app.core.errors import error_payload
from app.core.logging import setup_logging

setup_logging()
logger = structlog.get_logger(__name__)


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
    allow_origins=[
        origin.strip()
        for origin in settings.CORS_ALLOWED_ORIGINS.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    unsafe_method = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    api_request = request.url.path.startswith(settings.API_V1_STR)
    is_auth_entry = request.url.path in {
        f"{settings.API_V1_STR}/auth/login",
        f"{settings.API_V1_STR}/auth/register",
    }
    authorization = request.headers.get("authorization", "")
    bearer_authenticated = authorization.lower().startswith("bearer ")
    cookie_authenticated = bool(
        request.cookies.get("knowra_session") or request.cookies.get("knowra_refresh")
    )
    if (
        unsafe_method
        and api_request
        and not is_auth_entry
        and cookie_authenticated
        and not bearer_authenticated
    ):
        expected = request.cookies.get("knowra_csrf", "")
        supplied = request.headers.get("x-csrf-token", "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            correlation_id = str(
                getattr(request.state, "correlation_id", "csrf-rejected")
            )
            resp = JSONResponse(
                status_code=403,
                content=error_payload(403, "CSRF validation failed", correlation_id),
            )
            origin = request.headers.get("origin")
            allowed = [
                o.strip()
                for o in settings.CORS_ALLOWED_ORIGINS.split(",")
                if o.strip()
            ]
            if origin and (origin in allowed or "*" in allowed):
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp
    return await call_next(request)


@app.middleware("http")
async def structlog_middleware(request: Request, call_next):
    supplied = request.headers.get("x-correlation-id", "").strip()
    correlation_id = (
        supplied
        if re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", supplied)
        else str(uuid.uuid4())
    )
    clear_contextvars()
    bind_contextvars(
        correlation_id=correlation_id,
        run_id=correlation_id,
        method=request.method,
        path=request.url.path,
    )
    request.state.correlation_id = correlation_id
    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    finally:
        clear_contextvars()


def _correlation_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", "unknown"))


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.status_code, exc.detail, _correlation_id(request)),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    details = exc.errors()
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(error_payload(422, details, _correlation_id(request))),
    )


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.exception(
        "unhandled_request_error",
        correlation_id=_correlation_id(request),
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content=error_payload(
            500, "The request could not be completed", _correlation_id(request)
        ),
    )


@app.get("/health/live")
async def liveness():
    return {"status": "alive", "version": settings.VERSION}


@app.get("/health/ready")
async def readiness():
    components = await component_status(include_workers=False)
    status = overall_status(components)
    return JSONResponse(
        status_code=503 if status == "unready" else 200,
        content={"status": status, "components": components},
    )


@app.get("/health")
async def health_check():
    """Backward-compatible readiness alias for local tooling."""
    return await readiness()


@app.get(
    f"{settings.API_V1_STR}/diagnostics",
    dependencies=[Depends(require_user)],
    tags=["diagnostics"],
)
async def diagnostics():
    components = await component_status(include_workers=True)
    return {
        "status": overall_status(components),
        "components": components,
        "features": feature_status(),
        "model_downloads": {
            "automatic": settings.ALLOW_MODEL_DOWNLOADS,
            "policy": "Models and neural artifacts require explicit provisioning.",
        },
    }


app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(editor.router, prefix=settings.API_V1_STR)
protected = [Depends(get_principal)]
app.include_router(
    providers.router, prefix=settings.API_V1_STR, tags=["model providers"]
)
app.include_router(
    chat.router,
    prefix=f"{settings.API_V1_STR}/chat",
    tags=["chat"],
    dependencies=protected,
)
app.include_router(
    knowledge.router,
    prefix=settings.API_V1_STR,
    tags=["knowledge"],
    dependencies=protected,
)
app.include_router(
    runs.router, prefix=settings.API_V1_STR, tags=["runs"], dependencies=protected
)
app.include_router(
    execution.router,
    prefix=settings.API_V1_STR,
    tags=["execution"],
    dependencies=protected,
)
app.include_router(
    repositories.router,
    prefix=settings.API_V1_STR,
    tags=["repositories"],
    dependencies=protected,
)
app.include_router(
    workspaces.router,
    prefix=settings.API_V1_STR,
    tags=["workspaces"],
    dependencies=protected,
)
