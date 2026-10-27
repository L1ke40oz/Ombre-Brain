"""Owner erasure is authenticated, explicit, and independent of AI approval."""
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import frontmatter
import pytest
from starlette.responses import JSONResponse

import web.buckets as buckets_web
from ombrebrain.eventsourcing.ledger_replay import LedgerReplayValidator


@pytest.mark.asyncio
async def test_owner_erases_formal_memory_and_derived_state(bucket_mgr):
    bucket_id = await bucket_mgr.create(content="ordinary owner memory", domain=["life"])
    bucket = await bucket_mgr.get(bucket_id)
    bucket_mgr.embedding_engine = SimpleNamespace(delete_embedding=Mock())
    bucket_mgr.embedding_outbox = SimpleNamespace(discard=Mock())
    result = await bucket_mgr.permanently_delete_bucket(bucket_id)
    assert result["ok"]
    assert not Path(bucket["path"]).exists()
    assert await bucket_mgr.get(bucket_id) is None
    assert not any(b["id"] == bucket_id for b in await bucket_mgr.list_all(include_archive=True))
    bucket_mgr.embedding_engine.delete_embedding.assert_called_once_with(bucket_id)
    bucket_mgr.embedding_outbox.discard.assert_called_once_with(bucket_id)
    assert LedgerReplayValidator.default().validate(bucket_mgr.ledger_mirror.iter_events())["ok"]


@pytest.mark.asyncio
async def test_owner_erases_archived_memory_and_owned_attachment(bucket_mgr):
    bucket_id = await bucket_mgr.create(
        content="synthetic attachment", domain=["test"],
        media=[{"data_base64": base64.b64encode(b"test bytes").decode(), "filename": "sample.txt"}],
    )
    bucket = await bucket_mgr.get(bucket_id)
    attachment = Path(bucket_mgr.base_dir) / bucket["metadata"]["media"][0]["path"]
    assert attachment.exists()
    await bucket_mgr.archive(bucket_id)
    assert (await bucket_mgr.permanently_delete_bucket(bucket_id))["ok"]
    assert not attachment.exists()
    assert await bucket_mgr.get_including_archive(bucket_id) is None


@pytest.mark.asyncio
async def test_shared_and_unmanaged_attachments_are_preserved(bucket_mgr, tmp_path):
    first = await bucket_mgr.create(
        content="first", media=[{"data_base64": "eA==", "filename": "shared.txt"}],
    )
    source = await bucket_mgr.get(first)
    media = source["metadata"]["media"]
    shared = Path(bucket_mgr.base_dir) / media[0]["path"]
    second = await bucket_mgr.create(content="second")
    second_bucket = await bucket_mgr.get(second)
    post = frontmatter.load(second_bucket["path"])
    post["media"] = media
    frontmatter.dump(post, second_bucket["path"])
    outside = tmp_path / "unrelated.txt"
    outside.write_text("keep me")
    original = frontmatter.load(source["path"])
    original["media"].append({"path": str(outside), "stored": True})
    frontmatter.dump(original, source["path"])
    assert (await bucket_mgr.permanently_delete_bucket(first))["ok"]
    assert shared.read_bytes() == b"x"
    assert outside.read_text() == "keep me"
    assert await bucket_mgr.get(second) is not None


class FakeMCP:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def decorate(handler):
            for method in methods:
                self.routes[(method, path)] = handler
            return handler
        return decorate


class Request:
    def __init__(self, body):
        self.body = body


def wire(monkeypatch, bucket_mgr):
    monkeypatch.setattr(buckets_web.sh, "bucket_mgr", bucket_mgr, raising=False)
    async def read(request):
        return request.body
    monkeypatch.setattr(buckets_web.sh, "_read_json_object", read)
    mcp = FakeMCP()
    buckets_web.register(mcp)
    return mcp.routes[("POST", "/api/buckets/permanent-delete")]


@pytest.mark.asyncio
async def test_erasure_requires_login_and_explicit_confirmation(monkeypatch, bucket_mgr):
    handler = wire(monkeypatch, bucket_mgr)
    monkeypatch.setattr(buckets_web.sh, "_require_auth", lambda _: JSONResponse({}, status_code=401))
    assert (await handler(Request({"ids": ["abc"], "confirm": True}))).status_code == 401
    monkeypatch.setattr(buckets_web.sh, "_require_auth", lambda _: None)
    for value in [None, False, "true", 1]:
        assert (await handler(Request({"ids": ["abc"], "confirm": value}))).status_code == 400
    assert (await handler(Request({"ids": ["../outside"], "confirm": True}))).status_code == 400


@pytest.mark.asyncio
async def test_dashboard_owner_can_delete_without_ai_approval(monkeypatch, bucket_mgr):
    bucket_id = await bucket_mgr.create(content="owner-controlled memory")
    handler = wire(monkeypatch, bucket_mgr)
    monkeypatch.setattr(buckets_web.sh, "_require_auth", lambda _: None)
    response = await handler(Request({"ids": [bucket_id, bucket_id], "confirm": True}))
    result = json.loads(response.body)
    assert response.status_code == 200
    assert result["deleted"] == [bucket_id]
    assert result["ok"]
    assert await bucket_mgr.get(bucket_id) is None


@pytest.mark.asyncio
async def test_owner_reports_failed_index_cleanup(bucket_mgr):
    bucket_id = await bucket_mgr.create(content="index cleanup example")
    bucket_mgr.embedding_engine = SimpleNamespace(delete_embedding=Mock(side_effect=OSError("busy")))
    result = await bucket_mgr.permanently_delete_bucket(bucket_id)
    assert result["ok"]
    assert result["warnings"]
    assert await bucket_mgr.get(bucket_id) is None


@pytest.mark.asyncio
async def test_owner_cannot_erase_a_path_outside_vault(monkeypatch, bucket_mgr, tmp_path):
    outside = tmp_path / "unrelated.md"
    outside.write_text("must survive")
    monkeypatch.setattr(bucket_mgr, "_find_bucket_file", lambda _: str(outside))
    assert await bucket_mgr.permanently_delete_bucket("anything") == {"ok": False, "error": "unsafe_bucket_path"}
    assert outside.read_text() == "must survive"
