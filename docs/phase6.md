# Phase 6: semantic code RAG and Code Workspace

Phase 6 indexes software repositories as code symbols rather than generic text.
Repository intake supports bounded ZIP archives, credential-free HTTPS Git URLs
on configured hosts, and local paths under an explicitly controlled development
root. Tree-sitter extracts modules, functions, methods, classes, interfaces,
types, enums, signatures, docstrings, and exact one-based line ranges.

## Indexing pipeline

The repository worker performs these steps:

1. Safely unpack a ZIP, shallow-clone Git, or revalidate a controlled local path.
2. Respect the root `.gitignore`; prune `.git`, `node_modules`, `vendor`, build,
   cache, virtual-environment, and generated-output directories.
3. Detect supported source languages by extension.
4. Parse source with Tree-sitter and extract symbols, calls, and imports.
5. Replace the repository's SQL symbol/reference graph transactionally.
6. Embed bounded symbol source plus signature/docstring metadata.
7. Replace repository-filtered points in the `code_symbols_phase6` Qdrant
   collection and mark the repository ready.

Supported grammars currently include Python, JavaScript, TypeScript/TSX, Java,
Go, Rust, C/C++, and C#.

## Security boundaries

- ZIP entries are checked for traversal, absolute paths, symlinks, file count,
  archive size, and expanded size before writing.
- Git ingestion accepts credential-free HTTPS URLs only. Hosts must appear in
  `CODE_GIT_ALLOWED_HOSTS`.
- Local paths are disabled when `CODE_LOCAL_ROOT` is empty and must resolve
  beneath that root when enabled.
- `read_file` normalizes separators, rejects absolute and parent paths, resolves
  the final target, and verifies it remains inside the selected repository.
- Every SQL and Qdrant lookup is filtered by workspace and repository.
- Code tools are read-only: `search_code`, `read_file`, `find_references`, and
  `git_diff` cannot modify the worktree.

## Configuration

```dotenv
CODE_REPOSITORY_PATH=./data/repositories
CODE_LOCAL_ROOT=
CODE_GIT_ALLOWED_HOSTS=github.com,gitlab.com
CODE_COLLECTION=code_symbols_phase6
CODE_MAX_ARCHIVE_BYTES=52428800
CODE_MAX_EXTRACTED_BYTES=262144000
CODE_MAX_FILES=20000
CODE_MAX_SOURCE_BYTES=1048576
```

Compose persists managed repositories in `repository_data`. To enable local-path
ingestion inside containers, mount the intended host directory read-only into the
API and worker and set `CODE_LOCAL_ROOT` to that container path.

## API and user interface

Repository endpoints under `/api/v1/repositories` provide list/status, ZIP/Git/
local intake, reindexing, tree browsing, bounded file reads, symbol search,
semantic search, reference lookup, and Git diff inspection.

Open `/code` for the three-pane Code Workspace. It contains the repository tree,
a lazy-loaded read-only Monaco editor, symbol search, file/line navigation,
reference results, and Git diff panel. Code citations from chat link directly to
the repository file and line. Selecting a ready repository in chat scopes the
agent's code route and retrieval.

## Verification

From `backend`:

```powershell
uv run pytest tests
uv run ruff check app tests alembic
uv run ruff format --check app tests alembic
```

From `frontend`:

```powershell
npm test
npm run lint
npx tsc --noEmit
npm run build
```

Recorded on 2026-11-14: 38 backend tests passed and four opt-in live Docling
format tests were skipped. The 12-case Phase 6 suite covers Python and TypeScript
parsers, symbol lines, reference linking, ignored paths, ZIP and Git intake
security, traversal rejection, repository-scoped retrieval accuracy, and router
selection. Four frontend tests,
ESLint, TypeScript, the Webpack production build, Ruff, formatting, and dependency
lock resolution passed. Docker Compose configuration passed; a live Qdrant/Ollama
repository ingestion smoke test was not run because Docker Desktop was not
running.
