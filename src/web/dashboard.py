"""
========================================
web/dashboard.py — 仪表板页面 + 静态资源 + 健康检查
========================================

承载根路径仪表板、前端静态资源（icon/favicon/manifest/字体）、/favicon.ico 跳转、
以及 /health 健康检查。

对外暴露：register(mcp)。
========================================
"""

import os
import re
import hashlib
from functools import lru_cache

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh


@lru_cache(maxsize=256)
def _asset_digest(path, mtime_ns, size):
    with open(path, "rb") as asset:
        return hashlib.sha256(asset.read()).hexdigest()[:16]


def _asset_revision(name):
    path = os.path.join(sh.repo_root, "frontend", name)
    stat = os.stat(path)
    digest = _asset_digest(path, stat.st_mtime_ns, stat.st_size)
    if name.endswith((".css", ".js")) and name != "galaxy-engine.js":
        with open(path, encoding="utf-8") as asset:
            names = sorted(set(re.findall(r"/static/([A-Za-z0-9_-]+\.[a-z0-9]+)", asset.read())))
        dependencies = []
        for dependency in names:
            dep_path = os.path.join(sh.repo_root, "frontend", dependency)
            try:
                dep_stat = os.stat(dep_path)
                dependencies.append(_asset_digest(dep_path, dep_stat.st_mtime_ns, dep_stat.st_size))
            except OSError:
                continue
        digest = hashlib.sha256((digest + ''.join(dependencies)).encode()).hexdigest()[:16]
    return digest


def _version_assets(text):
    def replace(match):
        name = match.group(1)
        try:
            return f"/static/{name}?v={_asset_revision(name)}"
        except OSError:
            return match.group(0)
    return re.sub(r"/static/([A-Za-z0-9_-]+\.[a-z0-9]+)(?:\?v=[A-Za-z0-9.-]+)?", replace, text)


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
            # 别让浏览器缓存仪表板 HTML：否则改了 dashboard.html 重新下发后，
            # 用户看到的还是旧版面（U-09 只 cache-bust 了 SVG，HTML 本身没设）。
            # HTML 每次取最新入口，图片、字体和脚本则由内容版本复用缓存。
            return HTMLResponse(
                html,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
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
            "chime-self.webp": "image/webp",
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
            "login-flower-photo.webp": "image/webp",
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
        path = os.path.join(sh.repo_root, "frontend", name)
        try:
            with open(path, "rb") as f:
                payload = f.read()
            # Rewrite nested CSS/image/module URLs too. The public version is
            # content based, so redeploying identical files keeps phone caches.
            if media_type in {"text/css", "application/javascript"} and name != "galaxy-engine.js":
                payload = _version_assets(payload.decode("utf-8")).encode("utf-8")
            etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
            version = request.query_params.get("v")
            versioned = version == _asset_revision(name)
            headers = {
                "Cache-Control": "public, max-age=31536000, immutable" if versioned else "no-cache",
                "ETag": etag,
                "X-Content-Type-Options": "nosniff",
            }
            if request.headers.get("if-none-match") == etag:
                return _Resp(status_code=304, headers=headers)
            return _Resp(payload, media_type=media_type, headers=headers)
        except FileNotFoundError:
            return JSONResponse({"error": "not found"}, status_code=404)

    @mcp.custom_route("/sw.js", methods=["GET"])
    async def service_worker(request: Request) -> Response:
        with open(os.path.join(sh.repo_root, "frontend", "sw.js"), "rb") as script:
            return Response(script.read(), media_type="application/javascript", headers={
                "Cache-Control": "no-cache", "Service-Worker-Allowed": "/",
                "X-Content-Type-Options": "nosniff",
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
