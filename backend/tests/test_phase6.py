import asyncio
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.graph import classify_route
from app.code.parser import parse_source
from app.code.sources import (
    RepositorySourceError,
    extract_zip,
    iter_source_files,
    safe_repository_path,
    validate_git_url,
)
from app.code.workspace import CodeWorkspace
from app.core.config import settings
from app.models import (
    Base,
    CodeReference,
    Organization,
    Repository,
    Workspace,
)
from app.rag.code import CodeRetriever
from app.workers import code_ingest

PYTHON_FIXTURE = '''import os

def helper(value: str) -> str:
    """Normalize a value."""
    return value.strip()

class JwtValidator:
    def validate_jwt(self, token: str) -> str:
        """Validate a JWT token."""
        return helper(token)
'''

TYPESCRIPT_FIXTURE = """export interface TokenClaims { sub: string }
export class JwtService {
  validate(token: string): TokenClaims { return decodeToken(token); }
}
export const refreshToken = (token: string) => decodeToken(token);
"""


@pytest.fixture
def code_database(tmp_path: Path):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository_id = str(uuid.uuid4())
    root = tmp_path / "repository"
    root.mkdir()
    (root / "auth.py").write_text(PYTHON_FIXTURE, encoding="utf-8")
    with factory.begin() as session:
        session.add(Organization(id="org", name="Test"))
        session.add(
            Workspace(
                id=settings.LOCAL_WORKSPACE_ID,
                organization_id="org",
                name="Local",
            )
        )
        session.add(
            Repository(
                id=repository_id,
                workspace_id=settings.LOCAL_WORKSPACE_ID,
                name="Fixture",
                source_type="local",
                source_uri=str(root),
                root_path=str(root),
                status="ready",
            )
        )
    yield factory, repository_id, root
    engine.dispose()


def test_tree_sitter_extracts_python_symbols_and_lines():
    parsed = parse_source("auth.py", "python", PYTHON_FIXTURE)
    symbols = {symbol.name: symbol for symbol in parsed.symbols}
    assert {"auth", "helper", "JwtValidator", "validate_jwt"} <= set(symbols)
    assert symbols["helper"].kind == "function"
    assert symbols["helper"].start_line == 3
    assert symbols["validate_jwt"].qualified_name == "auth.JwtValidator.validate_jwt"
    assert symbols["validate_jwt"].docstring == "Validate a JWT token."


def test_tree_sitter_extracts_typescript_interfaces_methods_and_arrows():
    parsed = parse_source("src/auth.ts", "typescript", TYPESCRIPT_FIXTURE)
    values = {(symbol.name, symbol.kind) for symbol in parsed.symbols}
    assert ("TokenClaims", "interface") in values
    assert ("JwtService", "class") in values
    assert ("validate", "method") in values
    assert ("refreshToken", "function") in values


def test_reference_graph_links_calls_to_symbols(code_database, monkeypatch):
    factory, repository_id, _ = code_database
    monkeypatch.setattr(code_ingest, "SessionLocal", factory)
    parsed = parse_source("auth.py", "python", PYTHON_FIXTURE)
    code_ingest._persist_graph(
        repository_id,
        settings.LOCAL_WORKSPACE_ID,
        parsed.symbols,
        parsed.references,
    )
    references = CodeWorkspace(factory).find_references(
        repository_id, settings.LOCAL_WORKSPACE_ID, "helper"
    )
    assert len(references) == 1
    assert references[0]["file_path"] == "auth.py"
    assert references[0]["line"] == 10
    with factory() as session:
        reference = session.query(CodeReference).filter_by(target_name="helper").one()
        assert reference.source_symbol_id is not None
        assert reference.target_symbol_id is not None


@pytest.mark.parametrize(
    "path",
    ["../secret.py", "src/../../secret.py", "/etc/passwd", "C:\\Windows\\win.ini"],
)
def test_read_file_rejects_path_traversal(code_database, path: str):
    factory, repository_id, root = code_database
    with pytest.raises(RepositorySourceError):
        safe_repository_path(root, path)
    with pytest.raises(RepositorySourceError):
        CodeWorkspace(factory).read_file(
            repository_id, settings.LOCAL_WORKSPACE_ID, path
        )


def test_source_discovery_respects_gitignore_and_build_directories(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("def ignored(): pass", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "good.py").write_text("def good(): pass", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "bad.ts").write_text("const bad = 1", encoding="utf-8")
    files = [relative for _, relative, _ in iter_source_files(tmp_path)]
    assert files == ["src/good.py"]


def test_zip_ingestion_extracts_safe_files_and_rejects_traversal(
    tmp_path: Path, monkeypatch
):
    managed = tmp_path / "managed"
    managed.mkdir()
    monkeypatch.setattr(settings, "CODE_REPOSITORY_PATH", str(managed))
    archive = managed / "safe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("src/auth.py", "def validate(): pass")
    destination = managed / "safe" / "worktree"
    extract_zip(archive, destination)
    assert (destination / "src" / "auth.py").is_file()

    malicious = managed / "malicious.zip"
    with zipfile.ZipFile(malicious, "w") as bundle:
        bundle.writestr("../escape.py", "raise SystemExit")
    with pytest.raises(RepositorySourceError):
        extract_zip(malicious, managed / "malicious" / "worktree")
    assert not (managed / "malicious" / "escape.py").exists()


def test_git_ingestion_requires_allowed_credential_free_https(monkeypatch):
    monkeypatch.setattr(settings, "CODE_GIT_ALLOWED_HOSTS", "github.com")
    assert validate_git_url("https://github.com/openai/example.git").startswith(
        "https://github.com/"
    )
    for value in (
        "http://github.com/openai/example.git",
        "https://user:token@github.com/openai/example.git",
        "https://localhost/example.git",
        "https://gitlab.com/openai/example.git",
    ):
        with pytest.raises(RepositorySourceError):
            validate_git_url(value)


def test_code_retriever_returns_repository_scoped_symbol(code_database, monkeypatch):
    factory, repository_id, _ = code_database
    parsed = parse_source("auth.py", "python", PYTHON_FIXTURE)
    monkeypatch.setattr(code_ingest, "SessionLocal", factory)
    records = code_ingest._persist_graph(
        repository_id,
        settings.LOCAL_WORKSPACE_ID,
        parsed.symbols,
        parsed.references,
    )
    symbol_id = next(
        record["id"] for record in records if record["symbol"].name == "validate_jwt"
    )

    class FakeQdrant:
        async def collection_exists(self, name):
            return True

        async def query_points(self, **kwargs):
            return SimpleNamespace(points=[SimpleNamespace(id=symbol_id, score=0.91)])

        async def close(self):
            return None

    async def fake_embed(texts):
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr("app.rag.code.SessionLocal", factory)
    monkeypatch.setattr("app.rag.code.AsyncQdrantClient", lambda **kwargs: FakeQdrant())
    monkeypatch.setattr("app.rag.code.embed", fake_embed)
    result = asyncio.run(
        CodeRetriever().retrieve(
            "JWT validation",
            workspace_id=settings.LOCAL_WORKSPACE_ID,
            filters={"repository_id": repository_id},
        )
    )
    assert result.chunks[0].metadata["symbol"] == "validate_jwt"
    assert result.chunks[0].metadata["file_path"] == "auth.py"
    assert result.chunks[0].metadata["start_line"] == 8


def test_repository_selection_routes_to_code():
    assert classify_route("How does authentication work?", repository_id="repo") == (
        "code",
        ["code"],
    )
