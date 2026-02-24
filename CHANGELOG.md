# Changelog

All notable changes to **aiopyrus** will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/).

---
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
