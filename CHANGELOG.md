# Changelog

All notable changes to **aiopyrus** will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/).

---
## [0.5.0] — 2026-02-28

### Added
- **Batch concurrency limit**: `UserClient(max_concurrent=10)` — все batch-методы
  (`get_tasks`, `create_tasks`, `get_registers`, `download_print_forms` и др.)
  теперь ограничены семафором вместо неконтролируемого `asyncio.gather` на сотни
  параллельных запросов
- **Network retry**: `ConnectError`, `TimeoutException`, `ReadError` —
  автоматический retry через 5 секунд (один раз) вместо мгновенного падения
  при временном сбое сети
- **Auth lock**: `asyncio.Lock` на token refresh — конкурентные корутины
  не устраивают гонку из 10 одновременных POST на `/auth`
- **`request_raw(use_files_url=)`**: поддержка files-хоста для скачивания файлов

### Fixed
- **`upload_file`**: размер файла проверяется **до** чтения в память
  (`os.path.getsize` / `seek+tell`), а не после загрузки 260 МБ в `file_bytes`
- **`download_file`**: перенесён на `request_raw()` — проходит через
  rate limiter и auth lock вместо прямого `client.get()`
- **Polling memory leak**: `seen` dict теперь ограничен 10 000 записями
  с автоматическим удалением самых старых (раньше рос бесконечно в 24/7 ботах)
- **`SyncClient.close()`**: `try/finally` — event loop закрывается даже
  если `async close()` бросил исключение

### Changed
- **Default timeout**: 30s → 60s (рекомендация Pyrus для корпоративных инстансов)

---
## [0.4.0] — 2026-02-28

### Added
- **Approval helpers on Task model**: `get_approvals(step, choice=)`,
  `approvals_by_step` property, `get_approver_names()`, `get_approver_emails()`,
  `get_approver_ids()` — query approval steps by status without manual indexing
- **`find_member_by_email(email)`**: exact case-insensitive email lookup,
  returns `Person | None`
- **`find_members_by_emails(emails)`**: batch email lookup,
  returns `{email: Person}` dict
- **File size validation**: `upload_file()` raises `PyrusFileSizeError`
  when file exceeds 250 MB (Pyrus API limit) — early client-side check
  instead of a cryptic server error
- **`PyrusFileSizeError`** exception (exported from top-level package)
- **`stream_register(predicate=...)`**: optional predicate callback
  to filter tasks during streaming without loading the full register

---
## [0.3.0] — 2026-02-28

### Added
- **JWT preemptive refresh**: token is refreshed proactively before expiry
  (parses `exp` claim from JWT, no external dependencies) instead of waiting
  for a 401 error — saves one wasted API round-trip per token cycle
- **URL helpers**: `get_task_url(task_id)`, `get_form_url(form_id)` —
  browser-ready links for tasks and forms (works for both cloud and on-premise)
- **`SyncClient`**: synchronous wrapper for scripts, notebooks, and simple
  integrations — all `UserClient` methods available as blocking calls
  (`from aiopyrus import SyncClient`)
- **`get_registers(form_ids)`**: fetch multiple form registers in parallel,
  returns `{form_id: [Task, ...]}` dict (failed forms are skipped)
- **`stream_register(form_id)`**: memory-efficient streaming for large
  registers (10 000+ tasks) — yields `Task` objects one by one via
  incremental JSON parsing (no `ijson` dependency needed)
- **`PyrusSession.stream_get()`**: authenticated streaming GET for
  non-buffered response processing
- **`PyrusSession.web_base`**: browser-facing base URL property

---
## [0.2.0] — 2026-02-27

### Added
- **Batch operations**: `get_tasks()`, `create_tasks()`, `delete_tasks()`, `task_contexts()` —
  parallel task processing via `asyncio.gather`
- **Typed batch params**: `NewTask`, `NewRole`, `RoleUpdate`, `MemberUpdate` — Pydantic request models for batch methods
- **Batch roles/members**: `create_roles()`, `update_roles()`, `update_members()` — parallel org management
- **Task lists**: `get_lists()`, `get_task_list()` — task list (project/kanban) support
- **Print forms**: `download_print_form()`, `download_print_forms()` — PDF download (single & batch)
- **CSV export**: `get_register_csv()` — registry export as CSV text
- **Avatar**: `set_avatar()` — set member avatar by file GUID
- **External IDs**: `get_member_external_id()`, `get_members_external_ids()`,
  `get_roles_external_ids()` — AD/1C external ID resolution
- **Calendar enrichment**: `get_calendar()` now supports `filter_mask`, `all_accessed_tasks`,
  `item_count` parameters
- **`TaskList` model** — recursive model for task lists/projects with children
- **`FieldUpdate`** — smart field update builder: `text()`, `choice()`, `person()`, `catalog()`,
  `checkmark()`, `from_field()` (auto-detects format by field type)
- **`get_flat_fields()`** — recursive flatten of title/table nested fields
- **`format_mention()`** — HTML @mention builder for `formatted_text` fields
- **`select_fields()`** — client-side field projection from Pydantic models
- **`create_mock_client()`** — AsyncMock factory with `spec=UserClient` for testing
- **`PyrusSession.request_raw()`** — raw `httpx.Response` for non-JSON endpoints (PDF, CSV)
- `Person.external_id` field for corp/on-premise instances
- **Event Log (on-premise)**: `get_event_history()`, `get_file_access_history()`,
  `get_task_access_history()`, `get_task_export_history()`, `get_registry_download_history()` —
  audit CSV endpoints for Pyrus server instances

### Fixed
- **`comment_task()` attachments**: format `{"id": guid}` → `{"guid": guid}` — uploaded files
  now actually appear in comments (4 call sites: create_task, comment_task, announcements)
- **`TaskContext.reply()`**: Pyrus API ignores `reply_note_id` in the request body;
  now builds `<quote data-noteid="...">` in `formatted_text` to create proper threaded replies
- **Typed annotations**: `dict` → `PersonRef`, `dict[str, Any]`, `PrintFormItem` across
  public API (client, bot, webhook, params) for better IDE support
- **TaskContext pre-validation**: `approve()`, `reject()`, `finish()` now log
  `logging.warning()` when required fields for the current step are empty — Pyrus API
  silently accepts such requests but the step will not advance
- **`_collect_required_missing()`**: fixed `required_step` lookup to check both
  `FormField.required_step` attribute and `info["required_step"]` dict key

### Docs
- File attachment examples (comment + field) in README
- Approval step management (`approvals_rerequested`, `approvals_added`, `approvals_removed`)
- `ctx.answer(private=True)` documented in method table

## [0.1.9] — 2026-02-27

### Fixed
- Polling: clean one-liner error logging for network/API errors instead of full traceback
- Webhook `on_startup`/`on_shutdown` callbacks now work correctly (aiohttp `app` arg handled)
- `ApprovalPendingFilter` now exported from `aiopyrus` top-level package

### Added
- Linux integration tests (Fedora 43, Python 3.14): imports, Ctrl+C, webhook, error logging

## [0.1.8] — 2026-02-24

### Added
- Pyright added to CI pipeline (ruff + pyright + pytest on 3.10–3.14)
- GitHub Releases now auto-created from CHANGELOG on tag push
- `pyright` added to `[dev]` dependencies

## [0.1.7] — 2026-02-24

### Added
- Example `09_auto_processing.py` — UserClient: task processing by link
- Example `10_polling_auto_approve.py` — polling + FormFilter + StepFilter + ApprovalPendingFilter
- Example `11_http_integration.py` — HTTP server (aiohttp) for external systems (PHP, 1C, etc.)
- Example `12_embed_in_project.py` — embedding aiopyrus into FastAPI / Django / Celery / scripts

## [0.1.6] — 2026-02-24

### Fixed
- **Polling: `FormFilter` never matched** — `GET /register` omits `form_id` from
  the response; `start_polling()` now backfills it from the query parameter.
- `FieldType` enum: added missing `person_responsible`, `task_approval_date`,
  `task_approval_user` variants.
- `PrintTemplate.print_form_id` now optional (API sometimes omits it).

### Added
- Docstrings now document Pyrus API data availability per endpoint
  (inbox vs register vs get_task) — on `Task` model, `get_inbox()`,
  `get_register()`, `FormFilter`, `StepFilter`, `start_inbox_polling()`.
- `due_filter` values documented: `"overdue"`, `"overdue_on_step"`, `"past_due"`.
- New example `08_inbox_vs_register.py` — inbox vs register comparison,
  multi-form polling.
- README: new section "Inbox vs Register vs get_task".

## [0.1.5] — 2026-02-24

### Fixed
- On-premise `api_url` now correctly uses `/api/v4/` path
  (was `/v4/` which returns 404 on corp instances)

## [0.1.4] — 2026-02-24

### Added
- `base_url` param for on-premise: single URL instead of separate `api_url` + `auth_url`
  (accepts `"https://pyrus.mycompany.com"` or `"https://pyrus.mycompany.com/api/v4"`)
- `api_version` param (default `"v4"`)
- `ssl_verify` flag (default `True`) for self-signed certificates
- `.coverage` / `htmlcov/` added to `.gitignore`

### Changed
- On-premise setup simplified: `base_url` auto-derives both `api_url` and `auth_url`
- Old `api_url` / `auth_url` params kept for backwards compatibility

## [0.1.3] — 2026-02-24

### Fixed
- `FormField.duration` type: Pyrus returns `int` (e.g., `60` for 60 minutes),
  but library expected `str`. Now accepts `int | str | None`.
- Correct trailing slash in derived `api_url` for corp instances

### Changed
- Version bump to 0.1.3


## [0.1.2] — 2026-02-23

### Fixed
- `pyproject.toml`: `dependencies` was accidentally inside `[project.urls]` —
  broke `pip install` on Python 3.10 ([#8](https://github.com/TimmekHW/aiopyrus/actions/runs/8))
- PyPI package now includes classifiers (Python 3.10–3.14) and LICENSE

### Added
- `LICENSE` (MIT)
- Downloads badge (pepy.tech)
- Test coverage expanded: 330 → 426 tests, 86% → 97%
- Automated PyPI publishing via GitHub Releases (trusted publishing)

## [0.1.1] — 2025-12-20

### Added
- README included in PyPI package metadata
- PyPI badges, FAQ sections in both READMEs
- CI workflow: ruff lint/format + pytest on Python 3.10–3.14
- Test suite: 330 tests across 10+ modules

### Fixed
- Ruff lint issues across codebase

## [0.1.0] — 2025-12-15

### Added
- `UserClient` — async client for Pyrus API (tasks, catalogs, members, roles, files, announcements)
- `PyrusBot` — bot client for webhooks and polling
- `Dispatcher` + `Router` — aiogram-style handler registration
- `TaskContext` — field-level read/write with lazy flush
- Webhook server (`aiohttp`) with signature verification
- Long-polling mode with backoff
- Magic filters (`F.field == value`, `F.text.contains(...)`, `&`, `|`, `~`)
- Built-in filters: `FormFilter`, `StepFilter`, `FieldValueFilter`, `EventFilter`, `TextFilter`
- `BaseMiddleware` support
- Rate limiter (per-minute / per-10-min)
- Full type annotations, `py.typed` marker
- On-premise / corp instance support via `api_url`
