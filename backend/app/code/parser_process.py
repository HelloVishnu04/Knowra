"""One bounded native parser process per file. Never executes repository code."""

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from app.code.parser import ParsedFile, ParsedReference, ParsedSymbol
from app.core.config import settings


class ParserFailure(ValueError):
    pass


def parse_isolated(path: str, language: str, source: str) -> ParsedFile:
    if len(source.encode("utf-8")) > settings.CODE_MAX_SOURCE_BYTES:
        raise ParserFailure("source_too_large")
    with tempfile.TemporaryDirectory(prefix="knowra-parser-") as directory:
        request = Path(directory) / "request.json"
        response = Path(directory) / "response.json"
        request.write_text(
            json.dumps({"path": path, "language": language, "source": source}),
            encoding="utf-8",
        )
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app.code.parser_process",
                    str(request),
                    str(response),
                    str(settings.CODE_PARSER_MEMORY_MB),
                ],
                cwd=Path(__file__).resolve().parents[2],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=settings.CODE_PARSER_TIMEOUT_SECONDS,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise ParserFailure("parser_timeout") from exc
        if result.returncode != 0 or not response.is_file():
            raise ParserFailure("parser_crashed")
        if response.stat().st_size > 32 * 1024 * 1024:
            raise ParserFailure("parser_output_too_large")
        try:
            data = json.loads(response.read_text(encoding="utf-8"))
            return ParsedFile(
                symbols=[ParsedSymbol(**item) for item in data["symbols"]],
                references=[ParsedReference(**item) for item in data["references"]],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ParserFailure("parser_invalid_output") from exc


def main():
    if os.name != "nt":
        import resource

        memory = int(sys.argv[3]) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from app.code.parser import parse_source

    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    parsed = parse_source(data["path"], data["language"], data["source"])
    Path(sys.argv[2]).write_text(json.dumps(asdict(parsed)), encoding="utf-8")


if __name__ == "__main__":
    main()
