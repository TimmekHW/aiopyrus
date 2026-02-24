# Changelog

All notable changes to **aiopyrus** will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/).

---
## [0.1.3] — 2026-02-24

### Fixed
- `FormField.duration` type: Pyrus returns `int` (e.g., `60` for 60 minutes),
  but library expected `str`. Now accepts `int | str | None`.
- Documentation: on-premise examples now show correct `api_url` and `auth_url`
  format (e.g., `api_url="https://pyrus.mycompany.ru/v4"`,
  `auth_url="https://pyrus.mycompany.ru/api/v4/auth"`)

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
