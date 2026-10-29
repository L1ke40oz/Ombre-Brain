"""Public routes expose only constant-time, UI-essential information."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from web import auth as auth_web
from web import dashboard as dashboard_web
from web import meta as meta_web


class _MCP:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def decorator(handler):
            for method in methods:
                self.routes[(method, path)] = handler
            return handler

        return decorator


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,content_type",
    [
        ("login-cover.css", "text/css"),
        ("login-cover.js", "application/javascript"),
        ("dashboard-journal.css", "text/css"),
        ("dashboard-chime.js", "application/javascript"),
        ("dashboard-galaxy.js", "application/javascript"),
        ("dashboard-journal.js", "application/javascript"),
        ("sticker-bow.webp", "image/webp"),
        ("sticker-tape-gingham.webp", "image/webp"),
        ("chime-hook.webp", "image/webp"),
        ("chime-list.webp", "image/webp"),
        ("chime-breath.webp", "image/webp"),
        ("chime-network.webp", "image/webp"),
        ("chime-plan.webp", "image/webp"),
        ("chime-letters.webp", "image/webp"),
        ("chime-anchors.webp", "image/webp"),
        ("chime-import.webp", "image/webp"),
        ("chime-logs.webp", "image/webp"),
        ("chime-settings.webp", "image/webp"),
        ("login-sky.webp", "image/webp"),
        ("login-flower-photo.jpg", "image/jpeg"),
        ("login-crystal-pendant.webp", "image/webp"),
        ("login-plastic-clip.webp", "image/webp"),
        ("login-sticker-winter.webp", "image/webp"),
        ("login-sticker-sleep.webp", "image/webp"),
        ("login-rose-frame.webp", "image/webp"),
        ("login-paper-texture.svg", "image/svg+xml"),
        ("login-serif.woff2", "font/woff2"),
        ("login-serif-italic.woff2", "font/woff2"),
    ],
)
async def test_login_cover_assets_are_available_without_a_session(
    monkeypatch, name, content_type
):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(dashboard_web.sh, "repo_root", str(root))
    mcp = _MCP()
    dashboard_web.register(mcp)
    request = SimpleNamespace(path_params={"name": name})

    response = await mcp.routes[("GET", "/static/{name}")](request)

    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == content_type
    assert response.body == (root / "frontend" / name).read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [".env", "config.yaml", "../config.yaml", "login-other.js"])
async def test_login_cover_does_not_open_the_static_file_boundary(name):
    mcp = _MCP()
    dashboard_web.register(mcp)

    response = await mcp.routes[("GET", "/static/{name}")](
        SimpleNamespace(path_params={"name": name})
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_public_health_is_constant_time_and_minimal(monkeypatch):
    class ExplodingManager:
        async def get_stats(self):
            pytest.fail("public health must not walk the vault")

    monkeypatch.setattr(
        dashboard_web.sh,
        "bucket_mgr",
        ExplodingManager(),
        raising=False,
    )
    mcp = _MCP()
    dashboard_web.register(mcp)

    response = await mcp.routes[("GET", "/health")](object())

    assert json.loads(response.body) == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_public_auth_status_is_not_cacheable(monkeypatch):
    monkeypatch.setattr(auth_web.sh, "_is_authenticated", lambda _request: False)
    monkeypatch.setattr(auth_web.sh, "_is_setup_needed", lambda: True)
    mcp = _MCP()
    auth_web.register(mcp)

    response = await mcp.routes[("GET", "/auth/status")](object())

    assert json.loads(response.body) == {
        "authenticated": False,
        "setup_needed": True,
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_missing_dashboard_does_not_disclose_absolute_repo_path(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(dashboard_web.sh, "repo_root", str(tmp_path), raising=False)
    mcp = _MCP()
    dashboard_web.register(mcp)

    response = await mcp.routes[("GET", "/")](object())
    body = response.body.decode("utf-8")

    assert response.status_code == 404
    assert str(tmp_path) not in body
    assert "packaged frontend asset is missing" in body


@pytest.mark.asyncio
async def test_public_onboarding_omits_credential_sources_and_profile(
    monkeypatch,
):
    class Embedding:
        enabled = True

    monkeypatch.setenv("OMBRE_DASHBOARD_PASSWORD", "not-returned")
    monkeypatch.setenv("GEMINI_API_KEY", "also-not-returned")
    monkeypatch.setattr(meta_web.sh, "_load_password_hash", lambda: "hash")
    monkeypatch.setattr(
        meta_web.sh,
        "config",
        {
            "dehydration": {"api_key": "config-secret"},
            "deployment": {"profile": "private-profile", "onboarding_completed": True},
        },
    )
    monkeypatch.setattr(meta_web.sh, "embedding_engine", Embedding(), raising=False)
    mcp = _MCP()
    meta_web.register(mcp)

    response = await mcp.routes[("GET", "/api/onboarding/status")](object())
    payload = json.loads(response.body)

    assert payload == {"first_run": False, "embedding_enabled": True}
    assert response.headers["cache-control"] == "no-store"
