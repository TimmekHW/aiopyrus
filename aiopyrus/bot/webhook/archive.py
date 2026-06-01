from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("aiopyrus.webhook.archive")

# Process-wide monotonic counter. The event loop is single-threaded, so ``next()``
# between awaits is collision-free; combined with a microsecond timestamp it
# guarantees unique, lexicographically ordered filenames even when thousands of
# webhooks for the same task arrive in the same microsecond.
_seq = itertools.count(1)

# Anything that is not a safe filesystem token is collapsed to ``_``.
_UNSAFE = re.compile(r"[^0-9A-Za-z_-]")

#: Folder used when a webhook carries no resolvable task id.
NO_TASK_ID = "_no_task_id"


def _safe_name(value: str) -> str:
    name = _UNSAFE.sub("_", value)[:128]
    return name or "_"


def extract_task_id(payload_data: Any) -> str:
    """Best-effort extraction of the task id used as the folder name.

    Pyrus webhooks carry ``task_id`` at the top level; we also fall back to
    ``task.id`` for safety. Returns :data:`NO_TASK_ID` when nothing is found.
    """
    if isinstance(payload_data, dict):
        tid = payload_data.get("task_id")
        if tid is None:
            task = payload_data.get("task")
            if isinstance(task, dict):
                tid = task.get("id")
        if tid is not None:
            return _safe_name(str(tid))
    return NO_TASK_ID


def _body_as_json(raw_body: bytes) -> Any:
    """Return the parsed JSON body, or a faithful raw-text fallback when the
    body is not valid JSON (so even malformed webhooks are preserved)."""
    try:
        return json.loads(raw_body)
    except Exception:
        return {"_raw_text": raw_body.decode("utf-8", "replace")}


def _write_atomic(path: Path, data: bytes) -> None:
    """Synchronous, atomic single-file write (runs in a worker thread)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


async def save_raw_webhook(
    base_dir: str | Path,
    raw_body: bytes,
    payload_data: Any = None,
    *,
    headers: dict[str, str] | None = None,
) -> Path | None:
    """Persist a single incoming webhook to disk.

    Layout — **one folder per task, many files per folder**::

        <base_dir>/<task_id>/<YYYYMMDD_HHMMSS_ffffff>_<seq>.json

    Every delivery (including Pyrus retries and non-JSON bodies) is stored as a
    separate file, so a single task may accumulate anywhere from one to thousands
    of files. Each file is a self-describing envelope::

        {
          "received_at": "...ISO8601...",
          "task_id": "12345",
          "headers": {"X-Pyrus-Sig": "...", "X-Pyrus-Retry": "..."},
          "body": { ...exact webhook JSON... }   # or {"_raw_text": "..."} if not JSON
        }

    This function **never raises** — archiving must not break webhook handling.
    Disk I/O is offloaded to a worker thread to keep the event loop responsive.

    Returns the written path, or ``None`` on failure.
    """
    try:
        base = Path(base_dir)
        task_folder = extract_task_id(payload_data)
        now = datetime.now()
        seq = next(_seq)
        filename = f"{now:%Y%m%d_%H%M%S_%f}_{seq:06d}.json"
        target = base / task_folder / filename

        envelope = {
            "received_at": now.isoformat(),
            "task_id": None if task_folder == NO_TASK_ID else task_folder,
            "headers": headers or {},
            "body": _body_as_json(raw_body),
        }
        data = json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8")

        await asyncio.to_thread(_write_atomic, target, data)
        log.debug("Webhook archived: %s", target)
        return target
    except Exception:
        log.exception("Failed to archive webhook (processing continues)")
        return None
