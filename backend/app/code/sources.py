import shutil
import stat
import subprocess
import zipfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

from pathspec import PathSpec

from app.code.parser import detect_language
from app.core.config import settings

IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
    "venv",
}


class RepositorySourceError(ValueError):
    pass


def safe_repository_path(root: Path, relative_path: str) -> Path:
    if not relative_path or "\x00" in relative_path:
        raise RepositorySourceError("A relative repository path is required")
    normalized = relative_path.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise RepositorySourceError("Path traversal is not allowed")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise RepositorySourceError("Path escapes the repository root")
    return resolved


def validate_local_path(value: str) -> Path:
    if not settings.CODE_LOCAL_ROOT:
        raise RepositorySourceError("Local-path ingestion is disabled")
    allowed_root = Path(settings.CODE_LOCAL_ROOT).resolve()
    candidate = Path(value).resolve()
    if not candidate.is_dir() or not candidate.is_relative_to(allowed_root):
        raise RepositorySourceError("Local path is outside CODE_LOCAL_ROOT")
    return candidate


def validate_git_url(value: str) -> str:
    parsed = urlparse(value)
    allowed_hosts = {
        host.strip().lower()
        for host in settings.CODE_GIT_ALLOWED_HOSTS.split(",")
        if host.strip()
    }
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.hostname.lower() not in allowed_hosts
    ):
        raise RepositorySourceError(
            "Git URL must be credential-free HTTPS on an allowed host"
        )
    return value


def reset_managed_directory(path: Path) -> None:
    managed_root = Path(settings.CODE_REPOSITORY_PATH).resolve()
    resolved = path.resolve()
    if resolved == managed_root or not resolved.is_relative_to(managed_root):
        raise RepositorySourceError("Refusing to reset an unmanaged path")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def extract_zip(archive: Path, destination: Path) -> None:
    reset_managed_directory(destination)
    total_bytes = 0
    file_count = 0
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RepositorySourceError("ZIP symlinks are not allowed")
            file_count += 1
            total_bytes += info.file_size
            if file_count > settings.CODE_MAX_FILES:
                raise RepositorySourceError("ZIP contains too many files")
            if total_bytes > settings.CODE_MAX_EXTRACTED_BYTES:
                raise RepositorySourceError("ZIP expands beyond the configured limit")
            target = safe_repository_path(destination, info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def clone_git(url: str, destination: Path) -> None:
    validate_git_url(url)
    reset_managed_directory(destination)
    destination.rmdir()
    subprocess.run(
        ["git", "clone", "--depth", "1", "--", url, str(destination)],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _gitignore(root: Path) -> PathSpec:
    path = root / ".gitignore"
    lines = (
        path.read_text(encoding="utf-8", errors="replace").splitlines()
        if path.exists()
        else []
    )
    return PathSpec.from_lines("gitignore", lines)


def iter_source_files(root: Path) -> Iterator[tuple[Path, str, str]]:
    spec = _gitignore(root)
    seen = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            continue
        relative = path.relative_to(root).as_posix()
        if any(part in IGNORED_DIRECTORIES for part in path.relative_to(root).parts):
            continue
        if spec.match_file(relative):
            continue
        language = detect_language(path)
        if language is None or path.stat().st_size > settings.CODE_MAX_SOURCE_BYTES:
            continue
        seen += 1
        if seen > settings.CODE_MAX_FILES:
            raise RepositorySourceError("Repository contains too many source files")
        yield path, relative, language
