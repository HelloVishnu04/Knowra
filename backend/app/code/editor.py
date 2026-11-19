"""Personal snapshots and journaled, optimistic single-file edits on shared storage."""

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.audit import record_audit_event
from app.code.sources import IGNORED_DIRECTORIES
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.code import Repository
from app.models.editor import EditorWorkspace, FileMutation
from app.models.user import WorkspaceMember

RESERVED = {".git", ".editor-workspaces", ".write.lock"}


class EditorError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )


def safe_path(root: Path, value: str) -> Path:
    parts = value.replace("\\", "/").split("/")
    if not value or any(
        not part
        or part in {".", ".."}
        or part.lower() in RESERVED
        or part.endswith((".", " "))
        or re.search(r'[\x00-\x1f<>:"|?*]', part)
        or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
        for part in parts
    ):
        raise EditorError(
            422, "Use a relative file path without reserved names or traversal."
        )
    target = root
    for part in parts:
        target = target / part
        if os.path.lexists(target) and linked(target):
            raise EditorError(422, "Symbolic links and junctions cannot be edited.")
    if not target.resolve().is_relative_to(root.resolve()):
        raise EditorError(422, "Path escapes this working copy.")
    return target


def owner_key(principal):
    if principal.user_id:
        return "user:" + principal.user_id
    if settings.AUTH_REQUIRED:
        raise EditorError(401, "Sign in to open a personal working copy.")
    return "local"


def check_membership(session, principal, *, write=False):
    owner_key(principal)
    role = principal.role
    if principal.user_id:
        role = session.scalar(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == principal.workspace_id,
                WorkspaceMember.user_id == principal.user_id,
            )
        )
    if role not in {"owner", "administrator", "member", "viewer"}:
        raise EditorError(403, "Workspace access was revoked.")
    if write and role == "viewer":
        raise EditorError(403, "This workspace role is read-only.")


def area(workspace_id):
    key = str(uuid.UUID(workspace_id))
    managed = Path(settings.CODE_REPOSITORY_PATH).resolve()
    storage = managed / ".editor-workspaces"
    if storage.exists() and linked(storage):
        raise EditorError(409, "Editor storage is unavailable.")
    result = storage / key
    if result.exists() and linked(result):
        raise EditorError(409, "Working copy storage is unavailable.")
    for name in ("worktree", "snapshot"):
        child = result / name
        if os.path.lexists(child) and linked(child):
            raise EditorError(409, "Working copy storage is unavailable.")
    return result


@contextmanager
def mutation_lock(directory):
    lock_path = directory / ".write.lock"
    if not directory.is_dir() or (lock_path.exists() and linked(lock_path)):
        raise EditorError(409, "Working copy storage is unavailable.")
    with lock_path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise EditorError(409, "Another save is in progress. Try again.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def source_files(root, *, exclude_build=True):
    excluded = []
    paths = []
    for current, directories, files in os.walk(root, followlinks=False):
        current = Path(current)
        for name in list(directories):
            path = current / name
            if (
                (exclude_build and name in IGNORED_DIRECTORIES)
                or name.lower() in RESERVED
                or linked(path)
            ):
                directories.remove(name)
                excluded.append(path.relative_to(root).as_posix() + "/")
        for name in files:
            path = current / name
            relative = path.relative_to(root).as_posix()
            try:
                safe_path(root, relative)
            except EditorError:
                excluded.append(relative)
                continue
            if not path.is_file():
                excluded.append(relative)
                continue
            paths.append((relative, path))
            if len(paths) > settings.CODE_MAX_FILES:
                raise EditorError(413, "Working copy contains too many files.")
    return sorted(paths), sorted(excluded)


def file_hash(path):
    if not path.exists():
        return None
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def describe(data):
    bom = data.startswith(b"\xef\xbb\xbf")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "binary", "unknown", "Only UTF-8 text files can be edited."
    if "\x00" in text:
        return None, "binary", "unknown", "Binary files cannot be edited."
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    kinds = [name for name, count in (("crlf", crlf), ("lf", lf), ("cr", cr)) if count]
    newline = kinds[0] if len(kinds) == 1 else "mixed" if kinds else "lf"
    return (
        text.replace("\r\n", "\n").replace("\r", "\n"),
        "utf-8-bom" if bom else "utf-8",
        newline,
        "Mixed line endings are read-only to preserve the original bytes."
        if newline == "mixed"
        else None,
    )


def file_payload(path, data, revision):
    content, encoding, newline, reason = describe(data)
    return {
        "path": path,
        "version": digest(data),
        "content": content,
        "encoding": encoding,
        "newline": newline,
        "read_only_reason": reason,
        "size": len(data),
        "revision": revision,
    }


class EditorService:
    def __init__(self, session_factory=None):
        self.sessions = session_factory or SessionLocal

    def get(self, session, workspace_id, principal, *, write=False):
        check_membership(session, principal, write=write)
        item = session.get(EditorWorkspace, workspace_id)
        if (
            not item
            or item.workspace_id != principal.workspace_id
            or item.owner_key != owner_key(principal)
        ):
            raise EditorError(404, "Personal working copy not found.")
        return item

    @staticmethod
    def summary(item):
        return {
            "id": item.id,
            "repository_id": item.repository_id,
            "snapshot_hash": item.snapshot_hash,
            "revision": item.revision,
            "file_count": len(item.manifest_json),
            "excluded_paths": item.excluded_json,
            "created_at": item.created_at,
            "index_state": "not_indexed",
        }

    def list(self, principal, repository_id):
        with self.sessions() as session:
            check_membership(session, principal)
            rows = session.scalars(
                select(EditorWorkspace).where(
                    EditorWorkspace.workspace_id == principal.workspace_id,
                    EditorWorkspace.repository_id == repository_id,
                    EditorWorkspace.owner_key == owner_key(principal),
                )
            ).all()
            return [self.summary(item) for item in rows]

    def create(self, principal, repository_id):
        with self.sessions() as session:
            check_membership(session, principal, write=True)
            repository = session.get(Repository, repository_id)
            if not repository or repository.workspace_id != principal.workspace_id:
                raise EditorError(404, "Repository not found.")
            source = Path(repository.root_path).resolve()
        existing = self.list(principal, repository_id)
        if existing:
            return existing[0]
        if not source.is_dir():
            raise EditorError(409, "Repository files are not available yet.")
        workspace_id = str(uuid.uuid4())
        destination = area(workspace_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Temporary directory owns only this request's new files, never an existing copy.
        with tempfile.TemporaryDirectory(
            prefix=".creating-", dir=destination.parent
        ) as temporary:
            staging = Path(temporary)
            (staging / "snapshot").mkdir()
            (staging / "worktree").mkdir()
            paths, excluded = source_files(source)
            manifest = {}
            total = 0
            for relative, path in paths:
                with path.open("rb") as handle:
                    data = handle.read(settings.EDITOR_MAX_WORKSPACE_BYTES - total + 1)
                total += len(data)
                if total > settings.EDITOR_MAX_WORKSPACE_BYTES:
                    raise EditorError(
                        413, "Working copy exceeds the configured size limit."
                    )
                manifest[relative] = digest(data)
                for folder in ("snapshot", "worktree"):
                    target = safe_path(staging / folder, relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    shutil.copymode(path, target)
            current, current_excluded = source_files(source)
            if excluded != current_excluded or manifest != {
                relative: file_hash(path) for relative, path in current
            }:
                raise EditorError(409, "Source files changed while copying. Try again.")
            with self.sessions.begin() as session:
                check_membership(session, principal, write=True)
                item = EditorWorkspace(
                    id=workspace_id,
                    repository_id=repository_id,
                    workspace_id=principal.workspace_id,
                    owner_user_id=principal.user_id,
                    owner_key=owner_key(principal),
                    manifest_json=manifest,
                    excluded_json=excluded,
                    snapshot_hash=digest(json.dumps(manifest, sort_keys=True).encode()),
                )
                session.add(item)
                try:
                    session.flush()
                except IntegrityError:
                    session.rollback()
                    existing = self.list(principal, repository_id)
                    if existing:
                        return existing[0]
                    raise
                # Publish after uniqueness checks. DB failure may leave an orphan,
                # but can never expose a partial copy or overwrite another one.
                staging.rename(destination)
                record_audit_event(
                    session,
                    principal,
                    action="editor.created",
                    resource_type="editor_workspace",
                    resource_id=workspace_id,
                    details={
                        "repository_id": repository_id,
                        "snapshot_hash": item.snapshot_hash,
                    },
                )
                result = self.summary(item)
        return result

    def _recover(self, session, item, principal):
        pending = session.scalars(
            select(FileMutation).where(
                FileMutation.editor_workspace_id == item.id,
                FileMutation.state == "prepared",
            )
        ).all()
        for entry in pending:
            target = safe_path(area(item.id) / "worktree", entry.path)
            actual = file_hash(target)
            entry.state = (
                "applied"
                if actual == entry.after_hash
                else "aborted"
                if actual == entry.before_hash
                else "conflicted"
            )
            entry.finished_at = datetime.now(UTC)
            if entry.state == "applied":
                item.revision += 1
            record_audit_event(
                session,
                principal,
                action="editor.save_recovered",
                resource_type="editor_workspace",
                resource_id=item.id,
                details={
                    "path": entry.path,
                    "mutation_id": entry.id,
                    "state": entry.state,
                },
            )

    def read(self, workspace_id, principal, path):
        with self.sessions() as session:
            self.get(session, workspace_id, principal)
        with mutation_lock(area(workspace_id)), self.sessions.begin() as session:
            item = self.get(session, workspace_id, principal)
            self._recover(session, item, principal)
            target = safe_path(area(workspace_id) / "worktree", path)
            if not target.is_file():
                raise EditorError(404, "File not found.")
            with target.open("rb") as handle:
                data = handle.read(settings.EDITOR_MAX_FILE_BYTES + 1)
            if len(data) > settings.EDITOR_MAX_FILE_BYTES:
                raise EditorError(413, "File exceeds the editable size limit.")
            return file_payload(path, data, item.revision)

    def tree(
        self, workspace_id, principal, directory="", offset=0, limit=200, hidden=False
    ):
        with self.sessions() as session:
            self.get(session, workspace_id, principal)
        root = area(workspace_id) / "worktree"
        parent = safe_path(root, directory) if directory else root
        if not parent.is_dir():
            raise EditorError(404, "Directory not found.")
        entries = []
        for path in parent.iterdir():
            if (
                linked(path)
                or path.name.lower() in RESERVED
                or (not hidden and path.name.startswith("."))
            ):
                continue
            if not path.is_dir() and not path.is_file():
                continue
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "name": path.name,
                    "type": "directory" if path.is_dir() else "file",
                }
            )
        entries.sort(
            key=lambda entry: (entry["type"] != "directory", entry["name"].casefold())
        )
        return {
            "entries": entries[offset : offset + limit],
            "total": len(entries),
            "next_offset": offset + limit if offset + limit < len(entries) else None,
        }

    def write(self, workspace_id, principal, path, content, expected_version):
        with self.sessions() as session:
            self.get(session, workspace_id, principal, write=True)
        with mutation_lock(area(workspace_id)):
            with self.sessions.begin() as session:
                item = self.get(session, workspace_id, principal, write=True)
                self._recover(session, item, principal)
            target = safe_path(area(workspace_id) / "worktree", path)
            before = None
            if target.exists():
                if not target.is_file() or target.stat().st_nlink > 1:
                    raise EditorError(
                        422, "Only ordinary, unlinked files can be edited."
                    )
                with target.open("rb") as handle:
                    before = handle.read(settings.EDITOR_MAX_FILE_BYTES + 1)
                if len(before) > settings.EDITOR_MAX_FILE_BYTES:
                    raise EditorError(413, "File exceeds the editable size limit.")
            if (digest(before) if before is not None else None) != expected_version:
                raise EditorError(
                    409,
                    "File changed since it was opened. Review the latest version before saving.",
                )
            _, encoding, newline, reason = describe(before or b"")
            if reason:
                raise EditorError(422, reason)
            normalized = content.replace("\r\n", "\n").replace("\r", "\n")
            if "\x00" in normalized:
                raise EditorError(422, "Binary content cannot be saved as text.")
            data = normalized.replace(
                "\n", {"lf": "\n", "crlf": "\r\n", "cr": "\r"}[newline]
            ).encode("utf-8-sig" if encoding == "utf-8-bom" else "utf-8")
            if len(data) > settings.EDITOR_MAX_FILE_BYTES:
                raise EditorError(413, "File exceeds the editable size limit.")
            paths, _ = source_files(
                area(workspace_id) / "worktree", exclude_build=False
            )
            if (
                sum(p.stat().st_size for _, p in paths) - len(before or b"") + len(data)
                > settings.EDITOR_MAX_WORKSPACE_BYTES
            ):
                raise EditorError(
                    413, "Working copy exceeds the configured size limit."
                )
            if before is None and len(paths) >= settings.CODE_MAX_FILES:
                raise EditorError(413, "Working copy contains too many files.")
            mutation_id = str(uuid.uuid4())
            with self.sessions.begin() as session:
                self.get(session, workspace_id, principal, write=True)
                session.add(
                    FileMutation(
                        id=mutation_id,
                        editor_workspace_id=workspace_id,
                        path=path,
                        before_hash=expected_version,
                        after_hash=digest(data),
                        before_bytes=before,
                        after_bytes=data,
                    )
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=".save-", dir=area(workspace_id)
            )
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                if target.exists():
                    shutil.copymode(target, temporary)
                # Recheck external edits immediately before the atomic replacement.
                safe_path(area(workspace_id) / "worktree", path)
                if file_hash(target) != expected_version:
                    raise EditorError(
                        409, "File changed during the save. Review the latest version."
                    )
                with self.sessions.begin() as session:
                    item = self.get(session, workspace_id, principal, write=True)
                    os.replace(temporary, target)
                    if os.name != "nt":
                        directory_fd = os.open(target.parent, os.O_RDONLY)
                        try:
                            os.fsync(directory_fd)
                        finally:
                            os.close(directory_fd)
                    entry = session.get(FileMutation, mutation_id)
                    entry.state = "applied"
                    entry.finished_at = datetime.now(UTC)
                    item.revision += 1
                    record_audit_event(
                        session,
                        principal,
                        action="editor.file_saved",
                        resource_type="editor_workspace",
                        resource_id=workspace_id,
                        details={
                            "path": path,
                            "mutation_id": mutation_id,
                            "before_hash": expected_version,
                            "after_hash": entry.after_hash,
                        },
                    )
                    result = file_payload(path, data, item.revision)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return result
