import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.code.sources import RepositorySourceError, safe_repository_path


class PatchError(ValueError):
    """Raised when a generated unified diff is malformed or unsafe."""


@dataclass(frozen=True)
class PatchLine:
    operation: str
    text: str


@dataclass(frozen=True)
class PatchHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[PatchLine, ...]


@dataclass(frozen=True)
class FilePatch:
    old_path: str | None
    new_path: str | None
    hunks: tuple[PatchHunk, ...]

    @property
    def path(self) -> str:
        value = self.new_path or self.old_path
        if value is None:  # pragma: no cover - guarded by the parser
            raise PatchError("A file patch must have a path")
        return value


@dataclass(frozen=True)
class PatchSet:
    files: tuple[FilePatch, ...]

    @property
    def changed_files(self) -> list[str]:
        return [item.path for item in self.files]


HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")


def extract_unified_diff(value: str) -> str:
    """Extract one git-style unified diff from an LLM response."""
    text = value.strip()
    fenced = re.search(r"```(?:diff|patch)?\s*\n(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("diff --git ")
    if start < 0:
        raise PatchError("The model response did not contain a git-style unified diff")
    return text[start:].rstrip() + "\n"


def _normalize_path(value: str) -> str | None:
    value = value.split("\t", 1)[0]
    if value == "/dev/null":
        return None
    if value.startswith(("a/", "b/")):
        value = value[2:]
    path = PurePosixPath(value.replace("\\", "/"))
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or "\x00" in value
    ):
        raise PatchError(f"Unsafe patch path: {value!r}")
    return path.as_posix()


def parse_unified_diff(value: str, *, max_bytes: int = 500_000) -> PatchSet:
    if len(value.encode("utf-8")) > max_bytes:
        raise PatchError("Patch exceeds the configured size limit")
    lines = value.splitlines()
    files: list[FilePatch] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("diff --git "):
            if lines[index].strip():
                raise PatchError("Unexpected content outside a file diff")
            index += 1
            continue
        try:
            header = shlex.split(lines[index])
        except ValueError as exc:
            raise PatchError("Malformed diff header") from exc
        if len(header) != 4 or header[:2] != ["diff", "--git"]:
            raise PatchError("Malformed diff header")
        header_old = _normalize_path(header[2])
        header_new = _normalize_path(header[3])
        index += 1
        while index < len(lines) and not lines[index].startswith("--- "):
            metadata = lines[index]
            if metadata.startswith(
                (
                    "rename from ",
                    "rename to ",
                    "copy from ",
                    "copy to ",
                    "GIT binary patch",
                )
            ):
                raise PatchError("Rename, copy, and binary patches are not supported")
            if metadata.startswith("diff --git "):
                raise PatchError("File diff is missing ---/+++ headers")
            index += 1
        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise PatchError("File diff is missing ---/+++ headers")
        old_path = _normalize_path(lines[index][4:])
        new_path = _normalize_path(lines[index + 1][4:])
        if old_path is None and new_path is None:
            raise PatchError("A patch cannot read and write /dev/null")
        if old_path is not None and header_old != old_path:
            raise PatchError("Old file path does not match the diff header")
        if new_path is not None and header_new != new_path:
            raise PatchError("New file path does not match the diff header")
        index += 2
        hunks: list[PatchHunk] = []
        while index < len(lines) and not lines[index].startswith("diff --git "):
            if not lines[index].startswith("@@ "):
                if not lines[index].strip():
                    index += 1
                    continue
                raise PatchError("Unexpected content between patch hunks")
            match = HUNK_HEADER.match(lines[index])
            if match is None:
                raise PatchError("Malformed hunk header")
            old_start, old_count, new_start, new_count = (
                int(match.group(1)),
                int(match.group(2) or 1),
                int(match.group(3)),
                int(match.group(4) or 1),
            )
            index += 1
            patch_lines: list[PatchLine] = []
            while index < len(lines) and not lines[index].startswith(
                ("@@ ", "diff --git ")
            ):
                line = lines[index]
                if line == "\\ No newline at end of file":
                    index += 1
                    continue
                if not line or line[0] not in {" ", "+", "-"}:
                    raise PatchError("Every hunk line must start with space, +, or -")
                patch_lines.append(PatchLine(line[0], line[1:]))
                index += 1
            actual_old = sum(item.operation != "+" for item in patch_lines)
            actual_new = sum(item.operation != "-" for item in patch_lines)
            if actual_old != old_count or actual_new != new_count:
                raise PatchError("Hunk line counts do not match its header")
            hunks.append(
                PatchHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=tuple(patch_lines),
                )
            )
        if not hunks:
            raise PatchError("A file diff must contain at least one hunk")
        files.append(FilePatch(old_path, new_path, tuple(hunks)))
    if not files:
        raise PatchError("Patch contains no file changes")
    paths = [item.path for item in files]
    if len(paths) != len(set(paths)):
        raise PatchError("A patch may change each file only once")
    return PatchSet(tuple(files))


def _apply_file_patch(original: str, patch: FilePatch) -> str | None:
    source = original.splitlines()
    output: list[str] = []
    cursor = 0
    for hunk in patch.hunks:
        expected = max(0, hunk.old_start - 1)
        if expected < cursor or expected > len(source):
            raise PatchError(f"Hunk for {patch.path} starts outside the source file")
        output.extend(source[cursor:expected])
        cursor = expected
        for line in hunk.lines:
            if line.operation in {" ", "-"}:
                if cursor >= len(source) or source[cursor] != line.text:
                    raise PatchError(
                        f"Patch context does not match {patch.path} at line {cursor + 1}"
                    )
                if line.operation == " ":
                    output.append(line.text)
                cursor += 1
            else:
                output.append(line.text)
    output.extend(source[cursor:])
    if patch.new_path is None:
        if output:
            raise PatchError("Deleted file patch leaves content behind")
        return None
    result = "\n".join(output)
    if original.endswith("\n") or patch.old_path is None:
        result += "\n"
    return result


def apply_patch_in_memory(root: Path, patch_set: PatchSet) -> dict[str, str | None]:
    """Validate patch context against a repository without modifying any files."""
    results: dict[str, str | None] = {}
    for file_patch in patch_set.files:
        if file_patch.old_path is None:
            original = ""
            target = safe_repository_path(root, file_patch.path)
            if target.exists():
                raise PatchError(f"New file already exists: {file_patch.path}")
        else:
            try:
                target = safe_repository_path(root, file_patch.old_path)
            except RepositorySourceError as exc:
                raise PatchError(str(exc)) from exc
            if not target.is_file() or target.is_symlink():
                raise PatchError(
                    f"Patch source file does not exist: {file_patch.old_path}"
                )
            if target.stat().st_size > 2 * 1024 * 1024:
                raise PatchError(
                    f"Patch source file is too large: {file_patch.old_path}"
                )
            original = target.read_text(encoding="utf-8", errors="strict")
        results[file_patch.path] = _apply_file_patch(original, file_patch)
    return results
