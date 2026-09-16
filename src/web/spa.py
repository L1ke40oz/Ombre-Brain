"""
========================================
web/spa.py — 伺服构建好的 Vue 单页前端（frontend/app/），占据根路径
========================================

源码在同级仓库 ombre-brain-galaxy-mobile，`npm run build` 把产物写到
frontend/app/。这里把它挂在根上：

- /                     → dist 的 index.html
- /<任意子路径>          → 命中文件就发文件；没命中就回 index.html（history 兜底）

**注册顺序是承重的**：兜底路由是 `/{path:path}`，Starlette 按注册顺序匹配，
先注册者胜。所以 web/__init__.py 里 web.spa 必须排在**最后**，否则它会吃掉
全部 `/api/*`、`/auth/*`、`/oauth/*`。这条约束由
tests/test_spa_app_surface.py 钉住，别随手挪位置。

`/mcp` 由 mcp.streamable_http_app() 自己挂载，不走 custom_route；
_RESERVED_PREFIXES 里仍显式排除它，保证即使挂载顺序变了也不会被吞。

对外暴露：register(mcp)。
========================================
"""

import mimetypes
import os

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh

# 构建产物根目录。Dockerfile 的 `COPY frontend/ ./frontend/` 会把它带进镜像。
_DIST_SUBPATH = ("frontend", "app")

# 后端语义面：这些前缀下没匹配上的路径不该拿到 SPA 的 HTML。
# 纵深防御——正常情况下具体路由已先胜出，这里兜的是「打错的 API 路径」：
# 给等 JSON 的客户端回一篇 HTML 会让它在解析处炸，排查起来极其绕。
_RESERVED_PREFIXES = (
    "api/",
    "auth/",
    "oauth/",
    ".well-known/",
    "mcp",
    "static/",
    "breath-hook",
    "health",
)

# 带内容哈希的构建产物可以长缓存；index.html / SW 绝不能缓存，
# 否则用户拿到旧 index 去引用已被删掉的 chunk，白屏且刷新无效。
_IMMUTABLE_DIRS = ("assets",)
_NEVER_CACHE = {"index.html", "sw.js", "registerSW.js", "manifest.webmanifest"}


def _dist_root() -> str:
    return os.path.join(sh.repo_root, *_DIST_SUBPATH)


def _resolve_within(root: str, rel_path: str) -> str | None:
    """把请求路径安全地解析到 root 内部，越界就返回 None。

    安全要点：绝不能拿 request 里的字符串直接拼路径。`../../etc/passwd`、
    Windows 反斜杠、以及 symlink 都能跳出 dist。这里先规范化再用
    commonpath 做「真的在 root 底下」的判定（realpath 一并解掉 symlink）。
    """
    rel_path = rel_path.replace("\\", "/").lstrip("/")
    if not rel_path:
        return None
    # NUL 会让底层 open() 抛 ValueError，先挡掉当 404 处理。
    if "\x00" in rel_path:
        return None
    candidate = os.path.realpath(os.path.join(root, *rel_path.split("/")))
    root_real = os.path.realpath(root)
    try:
        if os.path.commonpath([candidate, root_real]) != root_real:
            return None
    except ValueError:
        # 不同盘符（Windows）时 commonpath 抛 ValueError —— 一律视作越界。
        return None
    return candidate


def _cache_headers(rel_path: str) -> dict:
    name = rel_path.rsplit("/", 1)[-1]
    if name in _NEVER_CACHE:
        return {"Cache-Control": "no-cache, no-store, must-revalidate"}
    top = rel_path.split("/", 1)[0]
    if top in _IMMUTABLE_DIRS:
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    return {"Cache-Control": "public, max-age=3600"}


def _index_response() -> Response:
    from starlette.responses import HTMLResponse

    index_path = os.path.join(_dist_root(), "index.html")
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
    except OSError:
        # 与 web/dashboard.py 同一条准则：不回显绝对路径，别把部署布局漏给公网。
        return HTMLResponse(
            "<h1>packaged frontend asset is missing</h1>"
            "<p>frontend/app/ 里没有构建产物。请在 ombre-brain-galaxy-mobile "
            "里跑 <code>npm run build</code>。</p>",
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )
    return HTMLResponse(html, headers=_cache_headers("index.html"))


def _is_reserved(rel_path: str) -> bool:
    lowered = rel_path.lstrip("/").lower()
    return any(lowered.startswith(prefix) for prefix in _RESERVED_PREFIXES)


def register(mcp) -> None:

    @mcp.custom_route("/", methods=["GET"])
    async def spa_root(request: Request) -> Response:
        """SPA 入口。鉴权交给前端自己：它会打 /api/*，401 时弹登录。"""
        return _index_response()

    @mcp.custom_route("/{path:path}", methods=["GET"])
    async def spa_asset(request: Request) -> Response:
        """先当静态文件发；不是文件就回 index.html（history 路由刷新兜底）。"""
        from starlette.responses import FileResponse, JSONResponse

        rel_path = request.path_params.get("path", "")

        # 走到这儿说明前面所有具体路由都没匹配上。后端语义面下的未知路径
        # 一律 JSON 404，不给 SPA 的 HTML（见 _RESERVED_PREFIXES）。
        if _is_reserved(rel_path):
            return JSONResponse(
                {"error": "not found"},
                status_code=404,
                headers={"Cache-Control": "no-store"},
            )

        full = _resolve_within(_dist_root(), rel_path)
        if full is None or not os.path.isfile(full):
            # /galaxy 这类前端路由走到这儿：交给 SPA 自己解析。
            return _index_response()

        media_type = mimetypes.guess_type(full)[0] or "application/octet-stream"
        return FileResponse(
            full,
            media_type=media_type,
            headers=_cache_headers(rel_path),
        )
