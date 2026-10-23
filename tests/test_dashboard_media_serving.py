"""Dashboard 附件可见性：/api/bucket/{id}/media/{filename} 的边界。

frontmatter 里一直存着 media 列表，但面板从来拿不到字节。补上这条路之后，
「哪个桶有附件、附件长什么样」在网页上第一次可见——同时它也成了记忆系统
第一个会把磁盘文件原样递出去的 HTTP 端点，所以边界要一次写死：
只认这个桶自己登记过的文件名，svg/html 一律走下载而不是就地渲染。
"""

import json
from pathlib import Path

import pytest

import web.buckets as buckets_web

_DASHBOARD_HTML = (
    Path(__file__).resolve().parent.parent / "frontend" / "dashboard.html"
)


class FakeMCP:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def decorator(handler):
            for method in methods:
                self.routes[(method, path)] = handler
            return handler

        return decorator


class MediaRequest:
    def __init__(self, bucket_id, filename):
        self.path_params = {"bucket_id": bucket_id, "filename": filename}
        self.query_params = {}


class ListRequest:
    def __init__(self):
        self.query_params = {}


class FakeMediaStore:
    def __init__(self, vault_dir):
        self.vault_dir = vault_dir
        self.media_dir = vault_dir / "_media"


class FakeBucketManager:
    def __init__(self, vault_dir, buckets):
        self.media_store = FakeMediaStore(vault_dir)
        self._buckets = {b["id"]: b for b in buckets}

    async def get(self, bucket_id):
        return self._buckets.get(bucket_id)

    async def list_all(self, *, include_archive=False):
        return list(self._buckets.values())


class FakeDecayEngine:
    def calculate_score(self, metadata):
        return 0.5


def _store_file(vault_dir, bucket_id, name, payload=b"fake-bytes"):
    """按 MediaStore 的真实布局落一个附件，返回 frontmatter 里那种相对路径。"""
    target_dir = vault_dir / "_media" / bucket_id
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / name).write_bytes(payload)
    return f"_media/{bucket_id}/{name}"


def _bucket(bucket_id, media=(), *, locked_letter=False):
    metadata = {
        "name": bucket_id,
        "created": "2026-10-01T00:00:00Z",
        "last_active": "2026-10-01T00:00:00Z",
        "media": [
            {"path": path, "sha256": "0" * 64, "size": 10, "stored": True}
            for path in media
        ],
    }
    if locked_letter:
        metadata.update(
            {"type": "letter", "lock_type": "permanent", "locked_by": "ai"}
        )
    return {"id": bucket_id, "metadata": metadata, "content": bucket_id}


def _wire(monkeypatch, vault_dir, buckets):
    monkeypatch.setattr(buckets_web.sh, "_require_auth", lambda _request: None)
    monkeypatch.setattr(
        buckets_web.sh,
        "bucket_mgr",
        FakeBucketManager(vault_dir, buckets),
        raising=False,
    )
    monkeypatch.setattr(
        buckets_web.sh, "decay_engine", FakeDecayEngine(), raising=False
    )
    mcp = FakeMCP()
    buckets_web.register(mcp)
    return mcp


async def _get_media(monkeypatch, tmp_path, buckets, bucket_id, filename):
    mcp = _wire(monkeypatch, tmp_path, buckets)
    handler = mcp.routes[("GET", "/api/bucket/{bucket_id}/media/{filename}")]
    return await handler(MediaRequest(bucket_id, filename))


@pytest.mark.asyncio
async def test_registered_image_is_served_inline(monkeypatch, tmp_path):
    relative = _store_file(tmp_path, "b1", "deadbeef.jpg")
    mcp = _wire(monkeypatch, tmp_path, [_bucket("b1", [relative])])
    handler = mcp.routes[("GET", "/api/bucket/{bucket_id}/media/{filename}")]

    response = await handler(MediaRequest("b1", "deadbeef.jpg"))

    assert response.status_code == 200
    assert response.path == str(tmp_path / "_media" / "b1" / "deadbeef.jpg")
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "private" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_unregistered_file_in_same_folder_is_not_reachable(monkeypatch, tmp_path):
    # 目录里躺着、但这个桶没登记过的文件：不给。否则「往 _media 里丢个文件
    # 就能通过面板读出来」会变成一条绕过记忆层的后门。
    _store_file(tmp_path, "b1", "listed.jpg")
    _store_file(tmp_path, "b1", "unlisted.jpg")
    relative = "_media/b1/listed.jpg"

    response = await _get_media(
        monkeypatch, tmp_path, [_bucket("b1", [relative])], "b1", "unlisted.jpg"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_other_buckets_attachment_is_not_reachable(monkeypatch, tmp_path):
    _store_file(tmp_path, "b1", "aaa.jpg")
    _store_file(tmp_path, "b2", "bbb.jpg")
    buckets = [
        _bucket("b1", ["_media/b1/aaa.jpg"]),
        _bucket("b2", ["_media/b2/bbb.jpg"]),
    ]

    # b2 的附件挂在 b1 名下要不到；即便文件名对上了，目录归属也会拦下来。
    assert (
        await _get_media(monkeypatch, tmp_path, buckets, "b1", "bbb.jpg")
    ).status_code == 404
    assert (
        await _get_media(monkeypatch, tmp_path, buckets, "b2", "bbb.jpg")
    ).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename",
    [
        "..",
        "../b1/deadbeef.jpg",
        "..\\..\\config.yaml",
        "/etc/passwd",
        "deadbeef.jpg/../../config.yaml",
        "",
    ],
)
async def test_path_shaped_filenames_never_resolve(monkeypatch, tmp_path, filename):
    relative = _store_file(tmp_path, "b1", "deadbeef.jpg")
    (tmp_path / "config.yaml").write_text("secret: true", encoding="utf-8")

    response = await _get_media(
        monkeypatch, tmp_path, [_bucket("b1", [relative])], "b1", filename
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_svg_is_downloaded_not_rendered(monkeypatch, tmp_path):
    # svg 能带脚本，inline 就等于在面板同源里执行；所以它走 attachment。
    relative = _store_file(tmp_path, "b1", "deadbeef.svg", b"<svg/>")

    response = await _get_media(
        monkeypatch, tmp_path, [_bucket("b1", [relative])], "b1", "deadbeef.svg"
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")


@pytest.mark.asyncio
async def test_locked_letter_hides_its_attachments(monkeypatch, tmp_path):
    relative = _store_file(tmp_path, "letter1", "deadbeef.jpg")
    bucket = _bucket("letter1", [relative], locked_letter=True)

    response = await _get_media(monkeypatch, tmp_path, [bucket], "letter1", "deadbeef.jpg")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_symlinked_attachment_is_refused(monkeypatch, tmp_path):
    relative = _store_file(tmp_path, "b1", "deadbeef.jpg")
    # 真建符号链接在 Windows 上要特权，这里直接让判定返回 True：
    # 端点必须因为「它是链接」而拒绝，而不是因为读不到。
    monkeypatch.setattr(buckets_web.os.path, "islink", lambda _path: True)

    response = await _get_media(
        monkeypatch, tmp_path, [_bucket("b1", [relative])], "b1", "deadbeef.jpg"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_missing_bucket_and_missing_file_are_404(monkeypatch, tmp_path):
    buckets = [_bucket("b1", ["_media/b1/gone.jpg"])]

    assert (
        await _get_media(monkeypatch, tmp_path, buckets, "nope", "gone.jpg")
    ).status_code == 404
    # 登记过、但文件已经不在了（换机器、清盘）：404，前端据此显示占位说明。
    assert (
        await _get_media(monkeypatch, tmp_path, buckets, "b1", "gone.jpg")
    ).status_code == 404


@pytest.mark.asyncio
async def test_bucket_list_reports_media_count(monkeypatch, tmp_path):
    relative = _store_file(tmp_path, "b1", "deadbeef.jpg")
    locked_relative = _store_file(tmp_path, "letter1", "cafe.jpg")
    buckets = [
        _bucket("b1", [relative]),
        _bucket("b2"),
        _bucket("letter1", [locked_relative], locked_letter=True),
    ]
    mcp = _wire(monkeypatch, tmp_path, buckets)

    response = await mcp.routes[("GET", "/api/buckets")](ListRequest())
    payload = json.loads(response.body.decode("utf-8"))

    counts = {item["id"]: item["media_count"] for item in payload}
    assert counts == {"b1": 1, "b2": 0, "letter1": 0}


def test_dashboard_renders_media_block():
    """面板侧：详情要画附件区，列表要画回形针，点开要看大图。"""
    html = _DASHBOARD_HTML.read_text(encoding="utf-8")
    assert "function renderMediaHtml(" in html
    assert "renderMediaHtml(id, meta.media)" in html
    assert "/media/' + encodeURIComponent(filename)" in html
    assert "openMediaLightbox" in html
    assert "media_count" in html
