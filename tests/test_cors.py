# The frontend is served from a different origin than this API (Vite dev
# server on :5173 locally, a static host in production), so a missing CORS
# allow-list silently breaks every browser call while curl/pytest calls
# (same-process, no Origin header enforcement) keep passing — this test
# exists so that regression is caught here instead of only in a browser.

from fastapi.testclient import TestClient

from app.main import app


def test_allowed_origin_gets_cors_headers() -> None:
    client = TestClient(app)
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_preflight_request_is_allowed_for_configured_origin() -> None:
    client = TestClient(app)
    response = client.options(
        "/auth/request-link",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_disallowed_origin_does_not_get_cors_headers() -> None:
    client = TestClient(app)
    response = client.get(
        "/health",
        headers={"Origin": "https://not-allow-listed.example.com"},
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
