from importlib.metadata import version

from fastapi.testclient import TestClient
from packaging.version import Version

from app import main
from app.api.dependencies import require_user
from app.core.diagnostics import overall_status
from app.core.errors import error_payload


def test_validated_tree_sitter_version_and_large_python_parse():
    # 0.26.0 caused native crashes on larger Python files in the Linux image.
    assert Version(version("tree-sitter")) < Version("0.26")

    from app.code.parser import parse_source

    source = "\n".join(
        f"def function_{number}(value):\n    return helper(value, {number})"
        for number in range(250)
    )
    parsed = parse_source("large_fixture.py", "python", source)
    assert len(parsed.symbols) == 251
    assert len(parsed.references) == 250


def test_health_status_distinguishes_required_and_optional_dependencies():
    assert (
        overall_status(
            {
                "database": {"required": True, "status": "available"},
                "qdrant": {"required": False, "status": "unavailable"},
            }
        )
        == "degraded"
    )
    assert (
        overall_status(
            {
                "database": {"required": True, "status": "unavailable"},
                "qdrant": {"required": False, "status": "available"},
            }
        )
        == "unready"
    )


def test_stable_error_envelope_keeps_legacy_detail():
    payload = error_payload(503, "Dependency unavailable", "correlation-123")
    assert payload["detail"] == "Dependency unavailable"
    assert payload["error"] == {
        "code": "service_unavailable",
        "message": "Dependency unavailable",
        "retryable": True,
        "correlation_id": "correlation-123",
    }


def test_liveness_and_error_response_include_correlation_id():
    client = TestClient(main.app)
    response = client.get(
        "/health/live", headers={"X-Correlation-ID": "phase9-test-correlation"}
    )
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "phase9-test-correlation"
    assert response.json()["status"] == "alive"

    missing = client.get(
        "/does-not-exist", headers={"X-Correlation-ID": "phase9-missing-route"}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert missing.json()["error"]["correlation_id"] == "phase9-missing-route"


def test_readiness_reports_degraded_optional_dependency(monkeypatch):
    async def fake_components(*, include_workers: bool = True):
        assert include_workers is False
        return {
            "database": {
                "status": "available",
                "required": True,
                "latency_ms": 1,
                "error": None,
            },
            "qdrant": {
                "status": "unavailable",
                "required": False,
                "latency_ms": 2,
                "error": "ConnectError",
            },
        }

    monkeypatch.setattr(main, "component_status", fake_components)
    response = TestClient(main.app).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_diagnostics_require_authentication_and_never_enable_model_downloads(
    monkeypatch,
):
    async def fake_components(*, include_workers: bool = True):
        assert include_workers is True
        return {
            "database": {
                "status": "available",
                "required": True,
                "latency_ms": 1,
                "error": None,
            }
        }

    monkeypatch.setattr(main, "component_status", fake_components)
    main.app.dependency_overrides[require_user] = lambda: object()
    try:
        response = TestClient(main.app).get("/api/v1/diagnostics")
    finally:
        main.app.dependency_overrides.pop(require_user, None)
    assert response.status_code == 200
    assert response.json()["model_downloads"]["automatic"] is False
