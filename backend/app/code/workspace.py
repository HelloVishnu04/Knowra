import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.code.sources import (
    IGNORED_DIRECTORIES,
    RepositorySourceError,
    safe_repository_path,
)
from app.core.database import SessionLocal
from app.models.code import CodeReference, CodeSymbol, Repository

SessionFactory = Callable[[], Session]


class CodeWorkspace:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self.session_factory = session_factory or SessionLocal

    def repository(self, repository_id: str, workspace_id: str) -> Repository:
        with self.session_factory() as session:
            repository = session.get(Repository, repository_id)
            if repository is None or repository.workspace_id != workspace_id:
                raise RepositorySourceError("Repository not found")
            session.expunge(repository)
            return repository

    def list_repositories(self, workspace_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = (
                session.query(Repository)
                .filter(Repository.workspace_id == workspace_id)
                .order_by(Repository.created_at.desc())
                .all()
            )
            return [
                {
                    "id": item.id,
                    "name": item.name,
                    "source_type": item.source_type,
                    "source_uri": item.source_uri
                    if item.source_type == "git"
                    else None,
                    "status": item.status,
                    "error": item.error,
                    "default_branch": item.default_branch,
                    "indexed_at": item.indexed_at.isoformat()
                    if item.indexed_at
                    else None,
                    "symbol_count": int(
                        (item.metadata_json or {}).get("symbol_count", 0)
                    ),
                    "file_count": int((item.metadata_json or {}).get("file_count", 0)),
                }
                for item in rows
            ]

    def tree(self, repository_id: str, workspace_id: str) -> list[dict[str, Any]]:
        repository = self.repository(repository_id, workspace_id)
        root = Path(repository.root_path).resolve()
        if repository.status != "ready" or not root.is_dir():
            return []
        entries: list[dict[str, Any]] = []
        for current, directories, files in os.walk(root):
            directories[:] = sorted(
                item for item in directories if item not in IGNORED_DIRECTORIES
            )
            current_path = Path(current)
            for name in [*directories, *sorted(files)]:
                path = current_path / name
                if path.is_symlink():
                    continue
                entries.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "name": name,
                        "type": "directory" if path.is_dir() else "file",
                    }
                )
                if len(entries) >= 10000:
                    return entries
        return entries

    def read_file(
        self,
        repository_id: str,
        workspace_id: str,
        path: str,
        *,
        start: int = 1,
        end: int | None = None,
    ) -> dict[str, Any]:
        repository = self.repository(repository_id, workspace_id)
        target = safe_repository_path(Path(repository.root_path), path)
        if not target.is_file() or target.is_symlink():
            raise RepositorySourceError("File not found")
        if target.stat().st_size > 2 * 1024 * 1024:
            raise RepositorySourceError("File is too large to display")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        first = max(1, start)
        last = min(len(lines), end if end is not None else first + 499)
        if last < first:
            raise RepositorySourceError("Invalid line range")
        return {
            "path": path,
            "language": target.suffix.lower().lstrip("."),
            "start_line": first,
            "end_line": last,
            "total_lines": len(lines),
            "content": "\n".join(lines[first - 1 : last]),
        }

    def search_symbols(
        self,
        repository_id: str,
        workspace_id: str,
        query: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self.repository(repository_id, workspace_id)
        pattern = f"%{query.strip()}%"
        with self.session_factory() as session:
            rows = (
                session.query(CodeSymbol)
                .filter(
                    CodeSymbol.repository_id == repository_id,
                    CodeSymbol.workspace_id == workspace_id,
                    or_(
                        CodeSymbol.name.ilike(pattern),
                        CodeSymbol.qualified_name.ilike(pattern),
                        CodeSymbol.signature.ilike(pattern),
                        CodeSymbol.file_path.ilike(pattern),
                    ),
                )
                .order_by(CodeSymbol.file_path, CodeSymbol.start_line)
                .limit(min(max(limit, 1), 100))
                .all()
            )
            return [self._symbol_json(item) for item in rows]

    def find_references(
        self, repository_id: str, workspace_id: str, symbol: str
    ) -> list[dict[str, Any]]:
        self.repository(repository_id, workspace_id)
        with self.session_factory() as session:
            rows = (
                session.query(CodeReference)
                .filter(
                    CodeReference.repository_id == repository_id,
                    CodeReference.target_name == symbol,
                )
                .order_by(CodeReference.file_path, CodeReference.line)
                .limit(200)
                .all()
            )
            return [
                {
                    "id": item.id,
                    "target_name": item.target_name,
                    "kind": item.kind,
                    "file_path": item.file_path,
                    "line": item.line,
                    "source_symbol_id": item.source_symbol_id,
                    "target_symbol_id": item.target_symbol_id,
                    **(item.metadata_json or {}),
                }
                for item in rows
            ]

    def git_diff(self, repository_id: str, workspace_id: str) -> dict[str, str]:
        repository = self.repository(repository_id, workspace_id)
        root = Path(repository.root_path).resolve()
        if not (root / ".git").is_dir():
            return {"diff": "", "message": "This repository has no Git worktree."}
        result = subprocess.run(
            ["git", "-C", str(root), "diff", "--no-ext-diff", "--unified=3"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RepositorySourceError("Unable to read Git diff")
        return {"diff": result.stdout[:500_000], "message": ""}

    @staticmethod
    def _symbol_json(item: CodeSymbol) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "qualified_name": item.qualified_name,
            "kind": item.kind,
            "language": item.language,
            "file_path": item.file_path,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "signature": item.signature,
            "docstring": item.docstring,
        }
