import hashlib
import json

import httpx
import pytest
from starlette.responses import JSONResponse

import web.meta as meta


class MCP:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def decorate(handler):
            for method in methods:
                self.routes[(method, path)] = handler
            return handler
        return decorate


def setup(monkeypatch, tmp_path, *, local="3.6.14", remote="3.6.14", same=False, config=None):
    monkeypatch.setattr(meta.sh, "config", config or {})
    monkeypatch.setattr(meta.sh, "repo_root", str(tmp_path))
    monkeypatch.setattr(meta.sh, "version", local)
    monkeypatch.setattr(meta.sh, "_require_auth", lambda _: None)
    (tmp_path / "frontend").mkdir()
    content = b"new content\n"
    (tmp_path / "frontend/dashboard.html").write_bytes(content.replace(b"\n", b"\r\n") if same else b"old content")
    manifest = {"files": [{"path": "frontend/dashboard.html", "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}]}
    requested = []

    def transport(request):
        requested.append(str(request.url))
        if request.url.path.endswith("/VERSION"):
            return httpx.Response(200, text=remote)
        if request.url.path.endswith("/update_manifest.json"):
            return httpx.Response(200, json=manifest)
        return httpx.Response(404)

    client = httpx.AsyncClient
    monkeypatch.setattr(meta.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(transport), **kwargs))
    mcp = MCP()
    meta.register(mcp)
    return mcp, requested


@pytest.mark.asyncio
@pytest.mark.parametrize("same,available", [(False, True), (True, False)])
async def test_same_version_changes_are_found_and_crlf_is_not_a_false_update(monkeypatch, tmp_path, same, available):
    mcp, requested = setup(monkeypatch, tmp_path, same=same)
    response = await mcp.routes[("GET", "/api/update-check")](object())
    data = json.loads(response.body)
    assert response.status_code == 200
    assert data["has_update"] is available
    assert data["changed_files"] == int(not same)
    assert data["source"]["repo"] == "L1ke40oz/Ombre-Brain"
    assert all("L1ke40oz/Ombre-Brain" in url and "ref=main" in url for url in requested)


@pytest.mark.asyncio
async def test_checker_honors_configured_repo_and_ref(monkeypatch, tmp_path):
    mcp, requested = setup(monkeypatch, tmp_path, config={"update": {"repo": "P0luz/Ombre-Brain", "ref": "testing"}})
    data = json.loads((await mcp.routes[("GET", "/api/update-check")](object())).body)
    assert data["source"]["repo"] == "P0luz/Ombre-Brain"
    assert all("P0luz/Ombre-Brain" in url and "ref=testing" in url for url in requested)


@pytest.mark.asyncio
async def test_older_source_is_never_offered_as_an_update(monkeypatch, tmp_path):
    mcp, _ = setup(monkeypatch, tmp_path, remote="3.6.13")
    data = json.loads((await mcp.routes[("GET", "/api/update-check")](object())).body)
    assert data["is_downgrade"] and not data["has_update"]


@pytest.mark.asyncio
async def test_update_check_is_authenticated_and_disallowed_sources_do_not_fetch(monkeypatch, tmp_path):
    mcp, requested = setup(monkeypatch, tmp_path, config={"update": {"repo": "attacker/evil"}})
    monkeypatch.delenv("OMBRE_ALLOW_CUSTOM_UPDATE_REPO", raising=False)
    handler = mcp.routes[("GET", "/api/update-check")]
    assert (await handler(object())).status_code == 400
    monkeypatch.setattr(meta.sh, "_require_auth", lambda _: JSONResponse({}, status_code=401))
    assert (await handler(object())).status_code == 401
    assert requested == []


@pytest.mark.asyncio
async def test_installer_downloads_the_same_default_fork(monkeypatch, tmp_path):
    mcp, _ = setup(monkeypatch, tmp_path)
    downloaded = []

    async def download(_client, url, _path):
        downloaded.append(url)

    monkeypatch.setattr(meta, "_download_update_archive_to_file", download)
    monkeypatch.setattr(meta, "_inspect_update_archive", lambda _: {"target_version": "", "requirements_bytes": None, "requirements_lock_bytes": None, "plan": {"abort": "synthetic stop before writes"}})
    response = await mcp.routes[("POST", "/api/do-update")](object())
    events = [event async for event in response.body_iterator]
    assert downloaded == ["https://github.com/L1ke40oz/Ombre-Brain/archive/refs/heads/main.zip"]
    assert any("synthetic stop" in event for event in events)
    assert not meta._UPDATE_JOB_LOCK.locked()


@pytest.mark.asyncio
async def test_api_failure_falls_back_to_the_same_repo_and_ref():
    requested = []

    def transport(request):
        requested.append(str(request.url))
        return httpx.Response(403) if request.url.host == "api.github.com" else httpx.Response(200, text="3.6.14\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await meta._read_update_file(client, "L1ke40oz/Ombre-Brain", "main", "VERSION")
    assert result.strip() == "3.6.14"
    assert requested[0].startswith("https://api.github.com/repos/L1ke40oz/Ombre-Brain/")
    assert requested[1].startswith("https://raw.githubusercontent.com/L1ke40oz/Ombre-Brain/main/")


def test_invalid_manifest_cannot_read_outside_the_project(tmp_path):
    with pytest.raises(ValueError):
        meta._count_update_changes({"files": [{"path": "src/../../private.env", "sha256": "a" * 64}]}, str(tmp_path))
