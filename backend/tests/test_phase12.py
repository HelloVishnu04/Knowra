import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import Principal, get_principal
from app.code import editor
from app.core.config import settings
from app.main import app
from app.models import Base, Organization, Repository, User, Workspace, WorkspaceMember
from app.models.audit import AuditEvent
from app.models.editor import EditorWorkspace, FileMutation


@pytest.fixture
def editing(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    root = tmp_path / "source"
    root.mkdir()
    (root / "hello.py").write_bytes(b"def hello():\r\n    return 42\r\n")
    (root / "empty.txt").touch()
    (root / ".env.example").write_text("EXAMPLE=true\n", encoding="utf-8")
    with factory.begin() as session:
        session.add(Organization(id="org", name="Org"))
        session.add_all(
            [
                Workspace(id="workspace", organization_id="org", name="Team"),
                Workspace(id="other", organization_id="org", name="Other"),
            ]
        )
        alice = User(id="alice", email="alice@example.com", hashed_password="unused")
        bob = User(id="bob", email="bob@example.com", hashed_password="unused")
        session.add_all([alice, bob])
        session.add_all(
            [
                WorkspaceMember(
                    id="alice-member",
                    workspace_id="workspace",
                    user_id="alice",
                    role="owner",
                ),
                WorkspaceMember(
                    id="bob-member",
                    workspace_id="workspace",
                    user_id="bob",
                    role="administrator",
                ),
            ]
        )
        session.add(
            Repository(
                id="repo",
                workspace_id="workspace",
                name="Source",
                source_type="zip",
                root_path=str(root),
                source_state="available",
            )
        )
    monkeypatch.setattr(editor, "SessionLocal", factory)
    monkeypatch.setattr(settings, "CODE_REPOSITORY_PATH", str(tmp_path / "managed"))
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    principal = Principal(alice, "workspace", "owner")
    selected = {"principal": principal}
    app.dependency_overrides[get_principal] = lambda: selected["principal"]
    service = editor.EditorService(factory)
    yield (
        factory,
        service,
        principal,
        Principal(bob, "workspace", "administrator"),
        root,
        selected,
    )
    app.dependency_overrides.clear()
    engine.dispose()


def test_personal_snapshot_is_isolated_and_reopening_is_idempotent(editing):
    factory, service, alice, bob, root, _ = editing
    first = service.create(alice, "repo")
    second = service.create(bob, "repo")
    assert first["id"] != second["id"]
    assert service.create(alice, "repo")["id"] == first["id"]
    before = service.read(first["id"], alice, "hello.py")
    saved = service.write(
        first["id"],
        alice,
        "hello.py",
        "def edited():\n    return 7\n",
        before["version"],
    )
    assert saved["content"] == "def edited():\n    return 7\n"
    assert (
        editor.area(first["id"]) / "worktree" / "hello.py"
    ).read_bytes() == b"def edited():\r\n    return 7\r\n"
    assert (root / "hello.py").read_bytes() == b"def hello():\r\n    return 42\r\n"
    assert (editor.area(first["id"]) / "snapshot" / "hello.py").read_bytes() == (
        root / "hello.py"
    ).read_bytes()
    assert service.read(second["id"], bob, "hello.py")["version"] == before["version"]
    with factory() as session:
        assert session.get(EditorWorkspace, first["id"]).revision == 1
        entry = session.scalar(select(FileMutation))
        assert entry.state == "applied"
        assert entry.before_bytes == (root / "hello.py").read_bytes()
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "editor.file_saved")
        )
        assert "return 7" not in str(audit.details_json)


def test_same_workspace_admin_and_other_tenant_cannot_read_private_copy(editing):
    _, service, alice, bob, _, selected = editing
    copy = service.create(alice, "repo")
    client = TestClient(app)
    selected["principal"] = bob
    assert (
        client.get(
            f"/api/v1/editor-workspaces/{copy['id']}/file?path=hello.py"
        ).status_code
        == 404
    )
    assert client.get("/api/v1/editor-workspaces?repository_id=repo").json() == []
    selected["principal"] = Principal(alice.user, "other", "owner")
    assert client.get(f"/api/v1/editor-workspaces/{copy['id']}/tree").status_code == 403


def test_membership_downgrade_and_removal_are_rechecked(editing):
    factory, service, alice, _, _, _ = editing
    copy = service.create(alice, "repo")
    file = service.read(copy["id"], alice, "hello.py")
    with factory.begin() as session:
        session.get(WorkspaceMember, "alice-member").role = "viewer"
    assert service.read(copy["id"], alice, "hello.py")["version"] == file["version"]
    with pytest.raises(editor.EditorError) as failure:
        service.write(copy["id"], alice, "hello.py", "forbidden", file["version"])
    assert failure.value.status == 403
    with factory.begin() as session:
        session.delete(session.get(WorkspaceMember, "alice-member"))
    with pytest.raises(editor.EditorError, match="revoked"):
        service.read(copy["id"], alice, "hello.py")


def test_stale_save_returns_409_and_preserves_newer_content(editing):
    _, service, alice, _, _, _ = editing
    copy = service.create(alice, "repo")
    client = TestClient(app)
    url = f"/api/v1/editor-workspaces/{copy['id']}/file"
    version = client.get(url + "?path=hello.py").json()["version"]
    assert (
        client.put(
            url,
            json={"path": "hello.py", "content": "first", "expected_version": version},
        ).status_code
        == 200
    )
    conflict = client.put(
        url, json={"path": "hello.py", "content": "stale", "expected_version": version}
    )
    assert conflict.status_code == 409
    assert client.get(url + "?path=hello.py").json()["content"] == "first"
    assert (
        client.put(
            url, json={"path": "hello.py", "content": "missing hash"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        "/tmp/secret",
        "C:/Windows/secret",
        "a/../../b",
        ".git/config",
        "src/.git/config",
        "file:stream",
        "NUL",
        "a/CON.txt",
        "name.",
        "a//b",
        "a\x00b",
    ],
)
def test_file_writes_reject_unsafe_paths(editing, path):
    _, service, alice, _, _, _ = editing
    copy = service.create(alice, "repo")
    with pytest.raises(editor.EditorError) as failure:
        service.write(copy["id"], alice, path, "forbidden", None)
    assert failure.value.status == 422


def test_utf8_bom_newlines_and_empty_file_round_trip(editing):
    _, service, alice, _, root, _ = editing
    original = b"\xef\xbb\xbf" + "héllo\r\n".encode()
    (root / "bom.txt").write_bytes(original)
    copy = service.create(alice, "repo")
    file = service.read(copy["id"], alice, "bom.txt")
    assert file["encoding"] == "utf-8-bom"
    assert file["newline"] == "crlf"
    service.write(copy["id"], alice, "bom.txt", file["content"], file["version"])
    assert (editor.area(copy["id"]) / "worktree" / "bom.txt").read_bytes() == original
    empty = service.read(copy["id"], alice, "empty.txt")
    assert empty["content"] == ""
    assert (
        service.write(copy["id"], alice, "empty.txt", "", empty["version"])["size"] == 0
    )


@pytest.mark.parametrize("data", [b"a\r\nb\nc", b"\xff\xfe\x00a", b"hello\x00binary"])
def test_unsupported_text_formats_are_read_only(editing, data):
    _, service, alice, _, root, _ = editing
    (root / "unsupported").write_bytes(data)
    copy = service.create(alice, "repo")
    file = service.read(copy["id"], alice, "unsupported")
    assert file["read_only_reason"]
    with pytest.raises(editor.EditorError):
        service.write(copy["id"], alice, "unsupported", "lossy edit", file["version"])
    assert (editor.area(copy["id"]) / "worktree" / "unsupported").read_bytes() == data


def test_create_file_and_lazy_directory_pagination(editing):
    _, service, alice, _, _, _ = editing
    copy = service.create(alice, "repo")
    created = service.write(copy["id"], alice, "src/日本語.txt", "hello\n", None)
    assert created["content"] == "hello\n"
    first = service.tree(copy["id"], alice, limit=1)
    assert first["entries"][0]["type"] == "directory"
    assert first["next_offset"] == 1
    assert all(
        entry["name"] != ".env.example"
        for entry in service.tree(copy["id"], alice)["entries"]
    )
    assert any(
        entry["name"] == ".env.example"
        for entry in service.tree(copy["id"], alice, hidden=True)["entries"]
    )
    assert (
        service.tree(copy["id"], alice, "src")["entries"][0]["path"] == "src/日本語.txt"
    )


def test_interrupted_save_before_replace_is_aborted_without_losing_original(
    editing, monkeypatch
):
    factory, service, alice, _, _, _ = editing
    copy = service.create(alice, "repo")
    original = service.read(copy["id"], alice, "hello.py")

    def fail(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(editor.os, "replace", fail)
    with pytest.raises(OSError):
        service.write(copy["id"], alice, "hello.py", "edited", original["version"])
    assert service.read(copy["id"], alice, "hello.py")["version"] == original["version"]
    with factory() as session:
        assert session.scalar(select(FileMutation)).state == "aborted"


def test_interrupted_save_after_replace_recovers_once(editing, monkeypatch):
    factory, service, alice, _, _, _ = editing
    copy = service.create(alice, "repo")
    original = service.read(copy["id"], alice, "hello.py")
    audit = editor.record_audit_event

    def fail(session, principal, **kwargs):
        if kwargs["action"] == "editor.file_saved":
            raise RuntimeError("simulated database interruption")
        return audit(session, principal, **kwargs)

    monkeypatch.setattr(editor, "record_audit_event", fail)
    with pytest.raises(RuntimeError):
        service.write(copy["id"], alice, "hello.py", "edited", original["version"])
    for _ in range(2):
        assert service.read(copy["id"], alice, "hello.py")["content"] == "edited"
    with factory() as session:
        assert session.get(EditorWorkspace, copy["id"]).revision == 1
        assert session.scalar(select(FileMutation)).state == "applied"


def test_workspace_lock_prevents_overlapping_writes(editing):
    _, service, alice, _, _, _ = editing
    copy = service.create(alice, "repo")
    with (
        editor.mutation_lock(editor.area(copy["id"])),
        pytest.raises(editor.EditorError, match="Another save"),
    ):
        service.write(copy["id"], alice, "new.txt", "hello", None)


def test_copy_excludes_git_and_dependency_folders_and_reports_them(editing):
    _, service, alice, _, root, _ = editing
    for name in (".git", "node_modules"):
        (root / name).mkdir()
        (root / name / "file").write_text("excluded", encoding="utf-8")
    copy = service.create(alice, "repo")
    assert copy["excluded_paths"] == [".git/", "node_modules/"]
    assert not (editor.area(copy["id"]) / "worktree" / ".git").exists()


def test_changed_source_does_not_publish_a_snapshot(editing, monkeypatch):
    factory, service, alice, _, _, _ = editing
    monkeypatch.setattr(editor, "file_hash", lambda path: "changed")
    with pytest.raises(editor.EditorError, match="Source files changed"):
        service.create(alice, "repo")
    with factory() as session:
        assert session.scalar(select(EditorWorkspace)) is None


def test_write_quota_includes_new_dependency_directories(editing, monkeypatch):
    _, service, alice, _, _, _ = editing
    copy = service.create(alice, "repo")
    service.write(copy["id"], alice, "node_modules/one.txt", "x" * 100, None)
    monkeypatch.setattr(settings, "EDITOR_MAX_WORKSPACE_BYTES", 200)
    with pytest.raises(editor.EditorError, match="size limit"):
        service.write(copy["id"], alice, "node_modules/two.txt", "x" * 100, None)


def test_hardlinked_file_cannot_modify_an_external_file(editing, tmp_path):
    _, service, alice, _, _, _ = editing
    copy = service.create(alice, "repo")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    os.link(outside, editor.area(copy["id"]) / "worktree" / "linked.txt")
    with pytest.raises(editor.EditorError, match="unlinked"):
        service.write(
            copy["id"], alice, "linked.txt", "attack", editor.digest(b"outside")
        )
    assert outside.read_text() == "outside"
