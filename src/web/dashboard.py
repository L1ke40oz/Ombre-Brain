"""
========================================
web/dashboard.py — 仪表板页面 + 静态资源 + 健康检查
========================================

承载根路径仪表板、前端静态资源（icon/favicon/manifest/字体）、/favicon.ico 跳转、
以及 /health 健康检查。

对外暴露：register(mcp)。
========================================
"""

import gzip
import hashlib
import os
import re
from functools import lru_cache

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh

_ASSET_REF = re.compile(r"/static/([A-Za-z0-9_-]+\.[a-z0-9]+)(?:\?v=[A-Za-z0-9.-]+)?")
# 带内容版本号的资源长期缓存；文件内容一变，版本号随之变，手机会取新文件。
_IMMUTABLE = "public, max-age=31536000, immutable"
_TEXT_TYPES = {"text/css", "application/javascript", "application/manifest+json", "image/svg+xml"}


@lru_cache(maxsize=256)
def _file_digest(path, mtime_ns, size):
    with open(path, "rb") as asset:
        return hashlib.sha256(asset.read()).hexdigest()[:16]


def _frontend_path(name):
    return os.path.join(sh.repo_root, "frontend", name)


def _asset_revision(name, _seen=None):
    """内容哈希版本号。git pull 只改 mtime 不改内容时，版本不变、缓存继续有效。

    CSS/JS 里引用的其它静态资源也计入版本，图片换了样式表的地址也会跟着变。
    """
    path = _frontend_path(name)
    stat = os.stat(path)
    digest = _file_digest(path, stat.st_mtime_ns, stat.st_size)
    if name.endswith((".css", ".js", ".json")) and name != "galaxy-engine.js":
        seen = (_seen or set()) | {name}
        with open(path, encoding="utf-8") as asset:
            names = sorted(set(_ASSET_REF.findall(asset.read())) - seen)
        parts = [digest]
        for dependency in names:
            try:
                parts.append(_asset_revision(dependency, seen))
            except OSError:
                continue
        if len(parts) > 1:
            digest = hashlib.sha256("".join(parts).encode()).hexdigest()[:16]
    return digest


def _version_assets(text):
    def replace(match):
        try:
            return f"/static/{match.group(1)}?v={_asset_revision(match.group(1))}"
        except OSError:
            return match.group(0)
    return _ASSET_REF.sub(replace, text)


def _accepts_gzip(request):
    headers = getattr(request, "headers", None) or {}
    return "gzip" in (headers.get("accept-encoding") or "").lower()


def _encoded(request, payload, headers, media_type):
    """文本资源按需 gzip；ETag 对应未压缩内容，压缩版加后缀区分。"""
    headers = dict(headers)
    if media_type.startswith("text/") or media_type in _TEXT_TYPES:
        headers["Vary"] = "Accept-Encoding"
        if len(payload) > 1024 and _accepts_gzip(request):
            payload = _gzip(payload)
            headers["Content-Encoding"] = "gzip"
            if "ETag" in headers:
                headers["ETag"] = headers["ETag"][:-1] + '-gz"'
    return payload, headers


@lru_cache(maxsize=16)
def _gzip(payload):
    return gzip.compress(payload, compresslevel=6, mtime=0)


def _not_modified(request, etag):
    headers = getattr(request, "headers", None) or {}
    sent = headers.get("if-none-match") or ""
    return bool(sent) and (sent == etag or sent == etag[:-1] + '-gz"')


def register(mcp) -> None:

    @mcp.custom_route("/", methods=["GET"])
    async def root_dashboard(request: Request) -> Response:
        """Serve dashboard HTML directly at root.

        历史上 / 会 307 → /dashboard，但叠加 Cloudflare Tunnel 的 Always Use HTTPS /
        Page Rule 时容易触发 ERR_TOO_MANY_REDIRECTS。直接返回 HTML，少一次跳转，
        既能修复回环，也省一个 RTT。
        """
        from starlette.responses import HTMLResponse
        dashboard_path = os.path.join(sh.repo_root, "frontend", "dashboard.html")
        try:
            with open(dashboard_path, "r", encoding="utf-8") as f:
                html = f.read()
            html = _version_assets(html)
            # HTML 入口每次向服务器确认（no-cache + ETag），内容没变只回 304，
            # 不再每次整页下载约 600 KB；图片、字体和脚本按内容版本长期缓存。
            payload = html.encode("utf-8")
            etag = '"' + hashlib.sha256(payload).hexdigest()[:32] + '"'
            headers = {"Cache-Control": "no-cache", "ETag": etag}
            if _not_modified(request, etag):
                return Response(status_code=304, headers=headers)
            payload, headers = _encoded(request, payload, headers, "text/html")
            return HTMLResponse(payload, headers=headers)
        except FileNotFoundError:
            # 走到这里 = 部署目录里缺 frontend/dashboard.html。它本应随仓库一起下发
            # （已纳入 git，未被 .gitignore 排除），最常见原因是克隆/部署了旧版本。
            return HTMLResponse(
                "<h1>dashboard.html not found</h1>"
                "<p>The packaged frontend asset is missing.</p>"
                "<p>This file ships with the repo (it is committed and NOT git-ignored). "
                "A missing file almost always means an outdated checkout — "
                "run <code>git pull origin main</code> / re-clone, or rebuild your Docker image, "
                "then restart.</p>",
                status_code=404,
            )

    # iter 1.7 §C/§H: serve frontend static assets (icon.svg, favicon.svg, manifest.json)
    # 安全要点：必须白名单过滤文件名，绝不能让 request 直接拼路径，
    # 否则会被 ?name=../../etc/passwd 这种「目录穿越」攻击拿走任意文件。
    @mcp.custom_route("/static/{name}", methods=["GET"])
    async def static_asset(request: Request) -> Response:
        from starlette.responses import Response as _Resp, JSONResponse
        name = request.path_params.get("name", "")
        allowed = {
            "icon.svg": "image/svg+xml",
            "favicon.svg": "image/svg+xml",
            "brand-icon.png": "image/png",
            "app-icon-180.png": "image/png",
            "app-icon-192.png": "image/png",
            "app-icon-512.png": "image/png",
            "app-icon-maskable-512.png": "image/png",
            "galaxy-engine.js": "application/javascript",
            "pwa.js": "application/javascript",
            "companion-idle.png": "image/png",
            "companion-idle.webp": "image/webp",
            "companion-lifted.png": "image/png",
            "manifest.json": "application/manifest+json",
            "RRPL.ttf": "font/truetype",
            "login-cover.css": "text/css",
            "login-cover.js": "application/javascript",
            "dashboard-journal.css": "text/css",
            "dashboard-chime.js": "application/javascript",
            "dashboard-galaxy.js": "application/javascript",
            "dashboard-journal.js": "application/javascript",
            "chime-hook.webp": "image/webp",
            "chime-list.webp": "image/webp",
            "chime-breath.webp": "image/webp",
            "chime-network.webp": "image/webp",
            "chime-plan.webp": "image/webp",
            "chime-letters.webp": "image/webp",
            "chime-anchors.webp": "image/webp",
            "chime-import.webp": "image/webp",
            "chime-logs.webp": "image/webp",
            "chime-settings.webp": "image/webp",
            "login-sky.webp": "image/webp",
            "login-flower-photo.jpg": "image/jpeg",
            "login-crystal-pendant.webp": "image/webp",
            "login-plastic-clip.webp": "image/webp",
            "login-sticker-winter.webp": "image/webp",
            "login-sticker-sleep.webp": "image/webp",
            "login-rose-frame.webp": "image/webp",
            "login-paper-texture.svg": "image/svg+xml",
            "login-serif.woff2": "font/woff2",
            "login-serif-italic.woff2": "font/woff2",
        }
        media_type = allowed.get(name)
        # 手账贴纸 / 吉祥物 / 风铃吊牌图：文件名限定为小写字母和连字符，不含路径分隔符
        if media_type is None and re.fullmatch(r"(?:sticker|mascot|chime)-[a-z-]+\.webp", name):
            media_type = "image/webp"
        if media_type is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        path = _frontend_path(name)
        try:
            with open(path, "rb") as f:
                payload = f.read()
            # 样式表、脚本里引用的图片字体也带上内容版本，一并长期缓存。
            if media_type in {"text/css", "application/javascript", "application/manifest+json"}                     and name != "galaxy-engine.js":
                payload = _version_assets(payload.decode("utf-8")).encode("utf-8")
            etag = '"' + hashlib.sha256(payload).hexdigest()[:32] + '"'
            query = getattr(request, "query_params", None) or {}
            versioned = bool(query.get("v")) and query.get("v") == _asset_revision(name)
            headers = {"Cache-Control": _IMMUTABLE if versioned else "no-cache", "ETag": etag}
            if _not_modified(request, etag):
                return _Resp(status_code=304, headers=headers)
            payload, headers = _encoded(request, payload, headers, media_type)
            return _Resp(payload, media_type=media_type, headers=headers)
        except FileNotFoundError:
            return JSONResponse({"error": "not found"}, status_code=404)

    # Service Worker 必须挂在根路径才能管理整个站点；它只缓存公开静态资源。
    @mcp.custom_route("/sw.js", methods=["GET"])
    async def service_worker(request: Request) -> Response:
        with open(_frontend_path("sw.js"), "rb") as script:
            return Response(script.read(), media_type="application/javascript", headers={
                "Cache-Control": "no-cache", "Service-Worker-Allowed": "/",
            })

    # 浏览器打开任意页都会自动请求 /favicon.ico，301 永久重定向到 SVG 版本。
    @mcp.custom_route("/favicon.ico", methods=["GET"])
    async def favicon_redirect(request: Request) -> Response:
        from starlette.responses import RedirectResponse
        return RedirectResponse(url="/static/brand-icon.png", status_code=301)

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> Response:
        from starlette.responses import JSONResponse
        # Public infrastructure probes must be O(1) and reveal no vault size,
        # engine state, filesystem path, or raw exception.  Authenticated
        # /api/status and /api/system/diagnostics own detailed health checks.
        return JSONResponse(
            {"status": "ok"},
            headers={"Cache-Control": "no-store"},
        )
