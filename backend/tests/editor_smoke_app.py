"""Disposable loopback-only API fixture for manually checking the editor UI.

Run from backend: python tests/editor_smoke_app.py
Use NEXT_PUBLIC_API_URL=http://localhost:8013 with a frontend on port 3013.
Every resource is temporary; no existing Knowra database or repository is used.
"""

import os
import sys
import tempfile
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with tempfile.TemporaryDirectory(prefix="knowra-editor-smoke-") as temporary:
        root = Path(temporary)
        os.environ.update({
            "DATABASE_URL": "sqlite:///" + (root / "test.db").as_posix(),
            "CODE_REPOSITORY_PATH": str(root / "managed"),
            "APP_ENVIRONMENT": "test", "AUTH_REQUIRED": "true",
            "CORS_ALLOWED_ORIGINS": "http://localhost:3013",
            "LANGGRAPH_CHECKPOINTER": "memory",
        })
        import uvicorn

        from app.api.dependencies import get_current_user
        from app.core.database import SessionLocal, engine
        from app.main import app
        from app.models import Base, Organization, Repository, User, Workspace, WorkspaceMember

        source = root / "source"
        source.mkdir()
        (source / "hello.py").write_bytes(b"def hello():\r\n    return 'Hello, Knowra'\r\n")
        (source / "README.md").write_text("# Editor test\n\nDisposable test content.\n", encoding="utf-8")
        Base.metadata.create_all(engine)
        with SessionLocal.begin() as session:
            user = User(id="smoke-user", email="editor-test@example.com", hashed_password="not-a-login")
            session.add(Organization(id="smoke-org", name="Test"))
            session.add(Workspace(id="smoke-workspace", organization_id="smoke-org", name="Test"))
            session.add(user)
            session.add(WorkspaceMember(id="smoke-member", workspace_id="smoke-workspace", user_id=user.id, role="owner"))
            session.add(Repository(id="smoke-repository", workspace_id="smoke-workspace", name="Editor smoke fixture", source_type="zip", root_path=str(source), source_state="available"))
        app.dependency_overrides[get_current_user] = lambda: user
        try:
            uvicorn.run(app, host="127.0.0.1", port=8013, lifespan="off")
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
