import asyncio
from collections.abc import AsyncGenerator

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.graph import AgentOrchestrator
from app.agents.traces import AgentTraceStore
from app.core.config import settings
from app.core.diagnostics import feature_status
from app.llm.base import LLMProvider
from app.models import Base, Citation, Organization, RetrievalRun, Workspace
from app.rag.web import (
    WebEgressError,
    WebRetriever,
    extract_html_text,
    parse_duckduckgo_html,
    validate_web_url,
)


class FakeProvider(LLMProvider):
    async def chat(self, messages: list[dict], model: str) -> str:
        return "Web-grounded answer [1]."

    async def stream_chat(
        self, messages: list[dict], model: str
    ) -> AsyncGenerator[str, None]:
        yield "Web-grounded "
        yield "answer [1]."


@pytest.fixture
def database():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(Organization(id="org", name="Test"))
        session.add(
            Workspace(
                id=settings.LOCAL_WORKSPACE_ID,
                organization_id="org",
                name="Local",
            )
        )
    yield factory
    engine.dispose()


def test_web_url_policy_blocks_private_and_disallowed_targets(monkeypatch):
    monkeypatch.setattr(settings, "WEB_BLOCK_PRIVATE_NETWORKS", True)
    monkeypatch.setattr(settings, "WEB_ALLOWED_DOMAINS", "")
    monkeypatch.setattr(settings, "WEB_BLOCKED_DOMAINS", "blocked.example")

    assert validate_web_url("https://docs.python.org/3/") == "https://docs.python.org/3/"

    for bad_url in (
        "file:///etc/passwd",
        "http://user:pass@example.com",
        "http://localhost:8000/secret",
        "http://127.0.0.1:8080",
        "http://169.254.169.254/latest/meta-data/",
        "https://sub.blocked.example/page",
    ):
        with pytest.raises(WebEgressError):
            validate_web_url(bad_url)

    monkeypatch.setattr(settings, "WEB_ALLOWED_DOMAINS", "python.org")
    assert validate_web_url("https://docs.python.org/3/") == "https://docs.python.org/3/"
    with pytest.raises(WebEgressError):
        validate_web_url("https://example.com/")


def test_html_and_duckduckgo_parsers():
    ddg_html = """
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Frelease&rut=abc">
        Example <b>Release</b> Notes
      </a>
      <a class="result__snippet">Version 2.0 launched today with web retrieval.</a>
    </div>
    """
    parsed = parse_duckduckgo_html(ddg_html, limit=5)
    assert parsed == [
        {
            "url": "https://example.com/release",
            "title": "Example Release Notes",
            "snippet": "Version 2.0 launched today with web retrieval.",
        }
    ]

    page_html = (
        "<html><head><title>Release Notes</title>"
        "<style>.hidden{display:none}</style></head>"
        "<body><script>alert(1)</script><h1>Headline</h1><p>Body &amp; text.</p></body></html>"
    )
    title, text = extract_html_text(page_html)
    assert title == "Release Notes"
    assert text == "Headline\nBody & text."


def test_web_retriever_searches_and_enriches_results(monkeypatch):
    monkeypatch.setattr(settings, "WEB_BLOCK_PRIVATE_NETWORKS", False)
    monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr(settings, "WEB_FETCH_PAGE_CONTENT", True)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(
                200,
                text=(
                    '<a class="result__a" href="https://example.com/a">Result A</a>'
                    '<a class="result__snippet">Snippet A</a>'
                    '<a class="result__a" href="https://example.com/b">Result B</a>'
                    '<a class="result__snippet">Snippet B</a>'
                ),
            )
        if str(request.url) == "https://example.com/a":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text="<html><head><title>Page A</title></head><body><p>Full content A</p></body></html>",
            )
        if str(request.url) == "https://example.com/b":
            return httpx.Response(403, text="Forbidden")
        return httpx.Response(404)

    retriever = WebRetriever(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        retriever.retrieve("latest release", workspace_id=settings.LOCAL_WORKSPACE_ID)
    )

    assert result.source == "web"
    assert len(result.chunks) == 2
    assert "Full content A" in result.chunks[0].content
    assert result.chunks[0].metadata["url"] == "https://example.com/a"
    assert result.chunks[0].metadata["title"] == "Page A"
    assert "Snippet B" in result.chunks[1].content
    assert result.chunks[1].metadata["url"] == "https://example.com/b"


def test_web_retriever_fetches_explicit_url_and_blocks_private_redirect(monkeypatch):
    monkeypatch.setattr(settings, "WEB_BLOCK_PRIVATE_NETWORKS", True)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://93.184.216.34/start":
            return httpx.Response(
                302, headers={"location": "http://127.0.0.1:8000/internal"}
            )
        if str(request.url) == "https://93.184.216.34/doc":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                text="Direct web document excerpt.",
            )
        return httpx.Response(404)

    retriever = WebRetriever(transport=httpx.MockTransport(handler))
    ok = asyncio.run(
        retriever.retrieve(
            "Summarize https://93.184.216.34/doc",
            workspace_id=settings.LOCAL_WORKSPACE_ID,
        )
    )
    assert len(ok.chunks) == 1
    assert "Direct web document excerpt." in ok.chunks[0].content

    with pytest.raises(RuntimeError, match="private or local network"):
        asyncio.run(
            retriever.retrieve(
                "https://93.184.216.34/start",
                workspace_id=settings.LOCAL_WORKSPACE_ID,
            )
        )


def test_orchestrator_runs_web_route_and_persists_web_citations(database, monkeypatch):
    monkeypatch.setattr(settings, "WEB_BLOCK_PRIVATE_NETWORKS", False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                '<a class="result__a" href="https://example.com/news">Breaking News</a>'
                '<a class="result__snippet">Important update from today.</a>'
            ),
        )

    monkeypatch.setattr(settings, "WEB_FETCH_PAGE_CONTENT", False)
    store = AgentTraceStore(database)
    orchestrator = AgentOrchestrator(
        provider=FakeProvider(),
        checkpointer=InMemorySaver(),
        trace_store=store,
        retrievers={"web": WebRetriever(transport=httpx.MockTransport(handler))},
    )
    state = orchestrator.initial_state(
        run_id="web-run-1",
        workspace_id=settings.LOCAL_WORKSPACE_ID,
        messages=[{"role": "user", "content": "What is the latest news today?"}],
        provider="fake",
        model="fake-model",
    )
    final = asyncio.run(orchestrator.run(state))
    assert final["route"] == "web"
    assert final["answer"] == "Web-grounded answer [1]."
    assert final["citations"][0]["source"] == "web"
    assert final["citations"][0]["url"] == "https://example.com/news"

    with database() as session:
        retrieval = session.scalar(
            select(RetrievalRun).where(RetrievalRun.agent_run_id == "web-run-1")
        )
        citation = session.scalar(
            select(Citation).where(Citation.agent_run_id == "web-run-1")
        )
        assert retrieval is not None
        assert retrieval.source == "web"
        assert retrieval.status == "completed"
        assert citation is not None
        assert citation.chunk_id is None
        assert citation.source == "web"
        assert citation.metadata_json["url"] == "https://example.com/news"


def test_diagnostics_reports_web_retrieval_status(monkeypatch):
    monkeypatch.setattr(settings, "WEB_RETRIEVAL_ENABLED", True)
    assert feature_status()["web_retrieval"]["status"] == "available"
    monkeypatch.setattr(settings, "WEB_RETRIEVAL_ENABLED", False)
    assert feature_status()["web_retrieval"]["status"] == "disabled"
