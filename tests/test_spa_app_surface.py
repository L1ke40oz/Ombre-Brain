"""web/spa.py 的边界契约。

这条路由带 `{path:path}` 通配，最容易犯的两个错是：遮住 `/api/*`，
以及让 `../../` 拿到 dist 外的文件。两条都在这里钉死。
"""

import os

import pytest

from web import spa as spa_web


class _MCP:
    """最小 FastMCP 替身：只收集 (method, path) → handler。"""

    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods=None):
        def deco(fn):
            for method in methods or ["GET"]:
                self.routes[(method, path)] = fn
            return fn

        return deco


class _Req:
    def __init__(self, path_params=None):
        self.path_params = path_params or {}


def _register(tmp_path, monkeypatch):
    monkeypatch.setattr(spa_web.sh, "repo_root", str(tmp_path), raising=False)
    mcp = _MCP()
    spa_web.register(mcp)
    return mcp


def _write_dist(tmp_path, files):
    dist = tmp_path / "frontend" / "app"
    for rel, content in files.items():
        target = dist / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return dist


def test_spa_must_be_registered_last():
    """承重约束：兜底路由 `/{path:path}` 按注册顺序匹配，先注册者胜。

    web.spa 一旦排在别的模块前面，就会吃掉它们全部的 /api/*、/auth/* 路由。
    """
    import web

    names = [name for name, _fn in web._WEB_MODULES]
    assert names[-1] == "web.spa", f"web.spa 必须是最后一个，当前顺序尾部：{names[-3:]}"


@pytest.mark.asyncio
async def test_missing_dist_does_not_disclose_absolute_repo_path(
    tmp_path, monkeypatch
):
    mcp = _register(tmp_path, monkeypatch)

    response = await mcp.routes[("GET", "/")](_Req())
    body = response.body.decode("utf-8")

    assert response.status_code == 404
    assert str(tmp_path) not in body
    assert "packaged frontend asset is missing" in body


@pytest.mark.asyncio
async def test_index_is_served_and_never_cached(tmp_path, monkeypatch):
    _write_dist(tmp_path, {"index.html": "<div id=app></div>"})
    mcp = _register(tmp_path, monkeypatch)

    response = await mcp.routes[("GET", "/")](_Req())

    assert response.status_code == 200
    assert b"id=app" in response.body
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_history_route_falls_back_to_index(tmp_path, monkeypatch):
    """刷新 /galaxy 必须回 index.html，而不是 404。"""
    _write_dist(tmp_path, {"index.html": "<div id=app></div>"})
    mcp = _register(tmp_path, monkeypatch)

    response = await mcp.routes[("GET", "/{path:path}")](
        _Req({"path": "galaxy"})
    )

    assert response.status_code == 200
    assert b"id=app" in response.body


@pytest.mark.asyncio
async def test_hashed_assets_get_immutable_cache(tmp_path, monkeypatch):
    _write_dist(tmp_path, {"assets/index-a1b2c3.js": "export default 1"})
    mcp = _register(tmp_path, monkeypatch)

    response = await mcp.routes[("GET", "/{path:path}")](
        _Req({"path": "assets/index-a1b2c3.js"})
    )

    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


@pytest.mark.parametrize(
    "attack",
    [
        "../../../etc/passwd",
        "..%2f..%2fsecret.txt",  # 已解码后仍是字面量，不该命中任何文件
        "....//....//secret.txt",
        "\\..\\..\\secret.txt",
        "/etc/passwd",
    ],
)
def test_traversal_never_escapes_dist(tmp_path, attack):
    """`_resolve_within` 是唯一的路径判定入口，逐个攻击串验一遍。"""
    dist = tmp_path / "frontend" / "app"
    dist.mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("leak", encoding="utf-8")

    resolved = spa_web._resolve_within(str(dist), attack)

    # 允许两种安全结局：判定为越界（None），或解析成 dist 内部的某个
    # 字面量名字（`....%2f` 这类没被 os 特殊处理，只是个不存在的文件名）。
    # 唯一不许发生的是拿到 dist 外面那个真文件。
    if resolved is not None:
        root = os.path.realpath(str(dist))
        assert os.path.commonpath([resolved, root]) == root
        assert resolved != os.path.realpath(str(secret))


@pytest.mark.asyncio
async def test_traversal_request_returns_index_not_file(tmp_path, monkeypatch):
    """整条路由端到端：穿越请求只会拿到 SPA 首页，拿不到 dist 外的文件。"""
    _write_dist(tmp_path, {"index.html": "<div id=app></div>"})
    (tmp_path / "secret.txt").write_text("leak", encoding="utf-8")
    mcp = _register(tmp_path, monkeypatch)

    response = await mcp.routes[("GET", "/{path:path}")](
        _Req({"path": "../../secret.txt"})
    )

    assert b"leak" not in response.body
    assert b"id=app" in response.body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "api/does-not-exist",
        "auth/nope",
        "oauth/nope",
        ".well-known/nope",
        "static/nope.svg",
        "mcp-extra",
        "breath-hook/x",
    ],
)
async def test_backend_prefixes_get_json_404_not_spa_html(
    tmp_path, monkeypatch, path
):
    """后端语义面下的未知路径必须回 JSON 404。

    给等 JSON 的客户端回一篇 HTML，会让它在 json.parse 处炸得莫名其妙。
    """
    _write_dist(tmp_path, {"index.html": "<div id=app></div>"})
    mcp = _register(tmp_path, monkeypatch)

    response = await mcp.routes[("GET", "/{path:path}")](_Req({"path": path}))

    assert response.status_code == 404
    assert b"id=app" not in response.body
    assert response.media_type == "application/json"
