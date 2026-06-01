"""Tests for the webhook archiver (one folder per task, many files per task)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from aiohttp.test_utils import TestClient, TestServer

from aiopyrus.bot.webhook.archive import NO_TASK_ID, extract_task_id, save_raw_webhook
from aiopyrus.bot.webhook.server import create_app


class TestExtractTaskId:
    def test_top_level_task_id(self):
        assert extract_task_id({"event": "x", "task_id": 42}) == "42"

    def test_nested_task_id(self):
        assert extract_task_id({"event": "x", "task": {"id": 7}}) == "7"

    def test_missing_task_id(self):
        assert extract_task_id({"event": "x"}) == NO_TASK_ID

    def test_non_dict(self):
        assert extract_task_id(None) == NO_TASK_ID

    def test_unsafe_chars_sanitised(self):
        assert extract_task_id({"task_id": "../etc/passwd"}) == "___etc_passwd"


class TestSaveRawWebhook:
    async def test_writes_envelope_under_task_folder(self, tmp_path: Path):
        body = json.dumps({"event": "task_created", "task_id": 100}).encode()
        path = await save_raw_webhook(
            tmp_path,
            body,
            {"event": "task_created", "task_id": 100},
            headers={"X-Pyrus-Retry": "0"},
        )
        assert path is not None
        assert path.parent.name == "100"
        env = json.loads(path.read_text(encoding="utf-8"))
        assert env["task_id"] == "100"
        assert env["headers"]["X-Pyrus-Retry"] == "0"
        assert env["body"] == {"event": "task_created", "task_id": 100}
        assert "received_at" in env

    async def test_many_webhooks_one_folder(self, tmp_path: Path):
        # 1 task → many files in the same folder (10..1000 webhooks per task)
        for i in range(25):
            body = json.dumps({"event": "comment", "task_id": 555, "n": i}).encode()
            await save_raw_webhook(tmp_path, body, {"task_id": 555, "n": i})
        folder = tmp_path / "555"
        files = sorted(folder.glob("*.json"))
        assert len(files) == 25
        # Filenames are time+seq ordered → sorted order matches insertion order
        first = json.loads(files[0].read_text(encoding="utf-8"))
        last = json.loads(files[-1].read_text(encoding="utf-8"))
        assert first["body"]["n"] == 0
        assert last["body"]["n"] == 24

    async def test_non_json_body_preserved(self, tmp_path: Path):
        path = await save_raw_webhook(tmp_path, b"not json{{{", None)
        assert path is not None
        assert path.parent.name == NO_TASK_ID
        env = json.loads(path.read_text(encoding="utf-8"))
        assert env["body"]["_raw_text"] == "not json{{{"

    async def test_never_raises_on_bad_dir(self, tmp_path: Path):
        # A clearly invalid path must not raise — archiving must never break handling.
        # We use a regular file masquerading as a directory: writing under it
        # will fail with NotADirectoryError, which save_raw_webhook must swallow.
        bad = tmp_path / "i_am_a_file"
        bad.write_text("x")
        result = await save_raw_webhook(str(bad), b"{}", {})
        # Must not raise. Result is None because the write failed.
        assert result is None


def _make_archiving_app(save_dir: Path):
    bot = MagicMock()
    bot.verify_signature = MagicMock(return_value=True)
    dp = MagicMock()
    dp.process_webhook = AsyncMock(return_value={})
    return create_app(
        dispatcher=dp, bot=bot, path="/pyrus", verify_signature=False, save_webhooks_dir=save_dir
    )


class TestHandlerArchiving:
    async def test_valid_webhook_is_archived(self, tmp_path: Path):
        app = _make_archiving_app(tmp_path)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/pyrus", json={"event": "task_received", "task_id": 42})
            assert resp.status == 200
        files = list((tmp_path / "42").glob("*.json"))
        assert len(files) == 1

    async def test_invalid_json_still_archived_and_400(self, tmp_path: Path):
        app = _make_archiving_app(tmp_path)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/pyrus", data=b"broken{{{")
            assert resp.status == 400
        files = list((tmp_path / NO_TASK_ID).glob("*.json"))
        assert len(files) == 1

    async def test_archiving_disabled_by_default(self, tmp_path: Path):
        bot = MagicMock()
        dp = MagicMock()
        dp.process_webhook = AsyncMock(return_value={})
        app = create_app(dispatcher=dp, bot=bot, path="/pyrus", verify_signature=False)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/pyrus", json={"event": "x", "task_id": 1})
            assert resp.status == 200
        # No files anywhere
        assert not list(tmp_path.rglob("*.json"))
