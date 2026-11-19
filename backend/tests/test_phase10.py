import json
from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_session
from app.core.provider_keys import rotate_provider_credentials
from app.core.security import decrypt_secret, encrypt_secret
from app.main import app
from app.models import (
    AuditEvent,
    AuthenticationThrottle,
    Base,
    KnowledgeBase,
    Organization,
    ProviderConfiguration,
    RefreshCredential,
    User,
    UserSession,
    Workspace,
    WorkspaceMember,
)


@pytest.fixture
def isolated_workspaces():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(Organization(id="org", name="Test organization"))
        users = {
            "alice": User(
                id="alice", email="alice@example.com", hashed_password="unused"
            ),
            "bob": User(id="bob", email="bob@example.com", hashed_password="unused"),
            "viewer": User(
                id="viewer", email="viewer@example.com", hashed_password="unused"
            ),
        }
        session.add_all(users.values())
        for workspace_id in ("workspace-a", "workspace-b", "workspace-viewer"):
            session.add(
                Workspace(
                    id=workspace_id,
                    organization_id="org",
                    name=workspace_id,
                )
            )
        session.add_all(
            [
                WorkspaceMember(
                    id="membership-a",
                    workspace_id="workspace-a",
                    user_id="alice",
                    role="owner",
                ),
                WorkspaceMember(
                    id="membership-b",
                    workspace_id="workspace-b",
                    user_id="bob",
                    role="member",
                ),
                WorkspaceMember(
                    id="membership-viewer",
                    workspace_id="workspace-viewer",
                    user_id="viewer",
                    role="viewer",
                ),
                KnowledgeBase(
                    id="kb-a", workspace_id="workspace-a", name="Alice knowledge"
                ),
                KnowledgeBase(
                    id="kb-b", workspace_id="workspace-b", name="Bob knowledge"
                ),
                KnowledgeBase(
                    id="kb-viewer",
                    workspace_id="workspace-viewer",
                    name="Viewer knowledge",
                ),
                ProviderConfiguration(
                    id="provider-a",
                    workspace_id="workspace-a",
                    user_id="alice",
                    name="Alice provider",
                    provider_type="ollama",
                    base_url="http://localhost:11434",
                    models_json=[],
                    is_enabled=True,
                ),
                ProviderConfiguration(
                    id="provider-b",
                    workspace_id="workspace-b",
                    user_id="bob",
                    name="Bob provider",
                    provider_type="ollama",
                    base_url="http://localhost:11434",
                    models_json=[],
                    is_enabled=True,
                ),
            ]
        )

    def sessions() -> Iterator[Session]:
        with factory() as session:
            yield session

    selected = {"user": users["alice"]}
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_current_user] = lambda: selected["user"]
    try:
        yield factory, selected, users
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_resource_and_provider_routes_are_scoped_to_membership(isolated_workspaces):
    _, selected, users = isolated_workspaces
    client = TestClient(app)

    assert [item["id"] for item in client.get("/api/v1/knowledge-bases").json()] == [
        "kb-a"
    ]
    assert client.get("/api/v1/knowledge-bases/kb-b/documents").status_code == 404
    assert (
        client.get(
            "/api/v1/knowledge-bases", headers={"X-Workspace-ID": "workspace-b"}
        ).status_code
        == 403
    )
    assert [item["id"] for item in client.get("/api/v1/providers").json()] == [
        "provider-a"
    ]

    selected["user"] = users["bob"]
    assert [item["id"] for item in client.get("/api/v1/knowledge-bases").json()] == [
        "kb-b"
    ]
    assert [item["id"] for item in client.get("/api/v1/providers").json()] == [
        "provider-b"
    ]


def test_private_provider_url_is_rejected_when_network_policy_is_enabled(
    isolated_workspaces, monkeypatch
):
    monkeypatch.setattr(settings, "PROVIDER_BLOCK_PRIVATE_NETWORKS", True)
    monkeypatch.setattr(settings, "PROVIDER_PRIVATE_HOST_ALLOWLIST", "")

    response = TestClient(app).post(
        "/api/v1/providers",
        json={
            "name": "Metadata endpoint",
            "provider_type": "openai_compatible",
            "base_url": "http://169.254.169.254/v1",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Provider URL targets a private or local network"
    )


def test_provider_mutations_are_audited_without_secrets(isolated_workspaces):
    factory, _, _ = isolated_workspaces
    client = TestClient(app)
    created = client.post(
        "/api/v1/providers",
        json={
            "name": "Hosted model",
            "provider_type": "openai_compatible",
            "base_url": "https://models.example/v1",
            "api_key": "super-secret-provider-key",
            "models": ["model-a"],
        },
    )
    assert created.status_code == 201
    provider_id = created.json()["id"]

    updated = client.put(
        f"/api/v1/providers/{provider_id}",
        json={
            "name": "Hosted model renamed",
            "provider_type": "openai_compatible",
            "base_url": "https://models.example/v1",
            "models": ["model-a"],
            "is_enabled": False,
        },
    )
    assert updated.status_code == 200
    assert client.delete(f"/api/v1/providers/{provider_id}").status_code == 204

    with factory() as session:
        events = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource_id == provider_id)
            .order_by(AuditEvent.created_at, AuditEvent.action)
        ).all()
    assert {event.action for event in events} == {
        "provider.created",
        "provider.updated",
        "provider.deleted",
    }
    serialized_details = str([event.details_json for event in events])
    assert "super-secret-provider-key" not in serialized_details


def test_provider_credentials_rotate_atomically_and_are_audited(
    isolated_workspaces, monkeypatch
):
    factory, _, _ = isolated_workspaces
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(
        settings,
        "PROVIDER_ENCRYPTION_KEYS",
        json.dumps({"old-v1": old_key, "new-v2": new_key}),
    )
    monkeypatch.setattr(settings, "PROVIDER_ENCRYPTION_ACTIVE_KEY_ID", "old-v1")
    with factory.begin() as session:
        config = session.get(ProviderConfiguration, "provider-a")
        config.api_key_encrypted = encrypt_secret("credential-to-rotate")
        config.api_key_version = "old-v1"

    monkeypatch.setattr(settings, "PROVIDER_ENCRYPTION_ACTIVE_KEY_ID", "new-v2")
    with factory() as session:
        result = rotate_provider_credentials(session)
    assert result.rotated == 1
    assert result.verified_current == 0

    monkeypatch.setattr(
        settings, "PROVIDER_ENCRYPTION_KEYS", json.dumps({"new-v2": new_key})
    )
    with factory() as session:
        config = session.get(ProviderConfiguration, "provider-a")
        assert config.api_key_version == "new-v2"
        assert decrypt_secret(config.api_key_encrypted) == "credential-to-rotate"
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "provider.secret_reencrypted")
        )
        assert event.actor_user_id is None
        assert event.details_json == {
            "previous_key_version": "old-v1",
            "key_version": "new-v2",
        }


def test_viewer_can_read_but_cannot_mutate(isolated_workspaces):
    _, selected, users = isolated_workspaces
    selected["user"] = users["viewer"]
    client = TestClient(app)

    response = client.get("/api/v1/knowledge-bases")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["kb-viewer"]
    denied = client.post("/api/v1/knowledge-bases", json={"name": "Forbidden"})
    assert denied.status_code == 403
    assert denied.json()["detail"] == "This workspace role is read-only"


def test_registration_creates_separate_owned_workspaces(isolated_workspaces):
    factory, _, _ = isolated_workspaces
    app.dependency_overrides.pop(get_current_user, None)

    first = TestClient(app).post(
        "/api/v1/auth/register",
        json={"email": "first@example.com", "password": "Password123"},
    )
    second = TestClient(app).post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": "Password123"},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["user"]["workspace_id"] != second.json()["user"]["workspace_id"]
    assert first.json()["user"]["role"] == second.json()["user"]["role"] == "owner"

    with factory() as session:
        memberships = session.scalars(
            select(WorkspaceMember).where(
                WorkspaceMember.user_id.in_(
                    [first.json()["user"]["id"], second.json()["user"]["id"]]
                )
            )
        ).all()
    assert len(memberships) == 2
    assert len({membership.workspace_id for membership in memberships}) == 2


def test_logout_revokes_the_server_session(isolated_workspaces):
    factory, _, _ = isolated_workspaces
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "logout@example.com", "password": "Password123"},
        headers={"User-Agent": "Knowra session test"},
    )
    assert registration.status_code == 201
    access_token = registration.json()["access_token"]
    csrf = client.cookies.get("knowra_csrf")
    assert csrf

    sessions = client.get("/api/v1/auth/sessions")
    assert sessions.status_code == 200
    assert len(sessions.json()) == 1
    assert sessions.json()[0]["current"] is True
    assert sessions.json()[0]["user_agent"] == "Knowra session test"

    missing_csrf = client.post("/api/v1/auth/logout")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["detail"] == "CSRF validation failed"
    assert client.get("/api/v1/auth/me").status_code == 200

    assert (
        client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code
        == 204
    )
    rejected = TestClient(app).get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert rejected.status_code == 401

    with factory() as session:
        record = session.scalar(select(UserSession).where(UserSession.user_agent != ""))
        assert record is not None
        assert record.revoked_at is not None


def test_refresh_rotation_detects_replay_and_revokes_session(isolated_workspaces):
    factory, _, _ = isolated_workspaces
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "rotation@example.com", "password": "Password123"},
    )
    assert registration.status_code == 201
    original_refresh = client.cookies.get("knowra_refresh")
    original_csrf = client.cookies.get("knowra_csrf")
    assert original_refresh
    assert original_csrf

    rotated = client.post(
        "/api/v1/auth/refresh", headers={"X-CSRF-Token": original_csrf}
    )
    assert rotated.status_code == 200
    assert client.cookies.get("knowra_refresh") != original_refresh

    replay = TestClient(app).post(
        "/api/v1/auth/refresh",
        headers={
            "Cookie": (
                f"knowra_refresh={original_refresh}; knowra_csrf={original_csrf}"
            ),
            "X-CSRF-Token": original_csrf,
        },
    )
    assert replay.status_code == 401
    assert replay.json()["detail"] == "Refresh credential reuse detected"
    assert client.get("/api/v1/auth/me").status_code == 401

    with factory() as session:
        credentials = session.scalars(select(RefreshCredential)).all()
        auth_session = session.scalar(select(UserSession))
        assert len(credentials) == 2
        assert sum(item.used_at is not None for item in credentials) == 1
        assert auth_session is not None
        assert auth_session.revoked_at is not None


def test_bearer_authenticated_mutation_does_not_require_csrf(isolated_workspaces):
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "bearer@example.com", "password": "Password123"},
    )
    token = registration.json()["access_token"]
    response = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Bearer workspace"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201


def test_cors_allows_only_configured_browser_origins(isolated_workspaces):
    client = TestClient(app)
    allowed = client.options(
        "/api/v1/knowledge-bases",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"

    denied = client.options(
        "/api/v1/knowledge-bases",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in denied.headers


def test_owner_manages_memberships_and_removal_revokes_workspace_access(
    isolated_workspaces,
):
    factory, selected, users = isolated_workspaces
    client = TestClient(app)

    added = client.post(
        "/api/v1/workspaces/current/members",
        json={"email": "bob@example.com", "role": "administrator"},
    )
    assert added.status_code == 201
    bob_membership_id = added.json()["id"]

    selected["user"] = users["bob"]
    workspace_headers = {"X-Workspace-ID": "workspace-a"}
    visible = client.get("/api/v1/knowledge-bases", headers=workspace_headers)
    assert visible.status_code == 200
    assert [item["id"] for item in visible.json()] == ["kb-a"]

    added_by_admin = client.post(
        "/api/v1/workspaces/current/members",
        json={"email": "viewer@example.com", "role": "member"},
        headers=workspace_headers,
    )
    assert added_by_admin.status_code == 201
    viewer_membership_id = added_by_admin.json()["id"]
    escalation = client.patch(
        f"/api/v1/workspaces/current/members/{viewer_membership_id}",
        json={"role": "owner"},
        headers=workspace_headers,
    )
    assert escalation.status_code == 403

    selected["user"] = users["alice"]
    removed = client.delete(f"/api/v1/workspaces/current/members/{bob_membership_id}")
    assert removed.status_code == 204

    selected["user"] = users["bob"]
    assert (
        client.get("/api/v1/knowledge-bases", headers=workspace_headers).status_code
        == 403
    )

    with factory() as session:
        actions = session.scalars(
            select(AuditEvent.action).order_by(AuditEvent.created_at)
        ).all()
    assert actions == [
        "workspace.member_added",
        "workspace.member_added",
        "workspace.member_removed",
    ]


def test_last_owner_cannot_be_demoted_or_removed(isolated_workspaces):
    _, _, _ = isolated_workspaces
    client = TestClient(app)
    members = client.get("/api/v1/workspaces/current/members").json()
    owner = next(member for member in members if member["role"] == "owner")

    demotion = client.patch(
        f"/api/v1/workspaces/current/members/{owner['id']}",
        json={"role": "member"},
    )
    assert demotion.status_code == 409
    removal = client.delete(f"/api/v1/workspaces/current/members/{owner['id']}")
    assert removal.status_code == 409


def test_workspace_audit_feed_is_admin_only(isolated_workspaces):
    _, selected, users = isolated_workspaces
    client = TestClient(app)
    client.post(
        "/api/v1/workspaces/current/members",
        json={"email": "bob@example.com", "role": "member"},
    )
    events = client.get("/api/v1/workspaces/current/audit-events")
    assert events.status_code == 200
    assert events.json()[0]["action"] == "workspace.member_added"

    selected["user"] = users["bob"]
    denied = client.get(
        "/api/v1/workspaces/current/audit-events",
        headers={"X-Workspace-ID": "workspace-a"},
    )
    assert denied.status_code == 403


def test_registration_can_be_disabled(isolated_workspaces, monkeypatch):
    app.dependency_overrides.pop(get_current_user, None)
    monkeypatch.setattr(settings, "REGISTRATION_ENABLED", False)
    response = TestClient(app).post(
        "/api/v1/auth/register",
        json={"email": "closed@example.com", "password": "Password123"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Account registration is disabled"
    assert TestClient(app).get("/api/v1/auth/config").json() == {
        "registration_enabled": False
    }


def test_failed_logins_are_persistently_throttled(isolated_workspaces):
    factory, _, _ = isolated_workspaces
    client = TestClient(app)
    payload = {"email": "bob@example.com", "password": "WrongPassword123"}

    assert [
        client.post("/api/v1/auth/login", json=payload).status_code for _ in range(4)
    ] == [
        401,
        401,
        401,
        401,
    ]
    limited = client.post("/api/v1/auth/login", json=payload)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == str(settings.AUTH_LOCKOUT_MINUTES * 60)

    with factory() as session:
        records = session.scalars(select(AuthenticationThrottle)).all()
    assert len(records) == 2
    assert all(record.locked_until is not None for record in records)


def test_successful_login_clears_previous_failures(isolated_workspaces):
    factory, _, _ = isolated_workspaces
    app.dependency_overrides.pop(get_current_user, None)
    registration = TestClient(app).post(
        "/api/v1/auth/register",
        json={"email": "recovered@example.com", "password": "Password123"},
    )
    assert registration.status_code == 201
    client = TestClient(app)
    wrong = {"email": "recovered@example.com", "password": "WrongPassword123"}
    assert client.post("/api/v1/auth/login", json=wrong).status_code == 401
    assert client.post("/api/v1/auth/login", json=wrong).status_code == 401
    successful = client.post(
        "/api/v1/auth/login",
        json={"email": "recovered@example.com", "password": "Password123"},
    )
    assert successful.status_code == 200

    with factory() as session:
        assert session.scalar(select(AuthenticationThrottle)) is None
