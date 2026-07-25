# Changelog

All notable changes to **aiopyrus** will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/).

---
## [0.10.0] — 2026-07-22

### Добавлено — поля-ссылки (`form_link`): чтение, автодополнение, переход

Поле-ссылка на задачу другой формы теперь полноценно поддержано —
как в интерфейсе, где есть поиск по заголовку.

- **`ctx["Поле-ссылка"]`** возвращает **читаемый заголовок** связанной
  задачи (`subject`), а не сырой dict. Если `subject` не пришёл —
  ID связанной задачи.

- **`await ctx.linked_task("Поле")`** — загрузить **саму связанную
  задачу** целиком (`Task` со всеми полями). `linked_tasks()` — для
  множественных ссылок.

- **`await ctx.search_link("Поле", "ABC-001")`** — автодополнение, как
  в интерфейсе: ищет кандидатов в связанной форме. Поле поиска
  подбирается автоматически (приоритет текстовым полям, в названии
  которых «номер» / «number» / «код» / «id» / «№»), либо задаётся явно
  через `search_field=`.

- **`ctx.fill("Поле", "ABC-001")`** — запись **по строке**: значение
  автоматически резолвится в ID связанной задачи через тот же поиск.
  Также принимает `int` / числовую строку (task_id) и `list[int]`.
  При нескольких совпадениях — явная ошибка со списком кандидатов,
  а не молчаливый выбор первого.

- **`await ctx.linked_form_id("Поле")`** — ID формы, на которую
  ссылается поле (берётся из определения формы).

- **`client.find_tasks_by_field(form_id, field, value)`** — поиск задач
  формы по значению поля (фильтр реестра `fld{id}=`). `field` — ID
  **или имя** поля. Совпадение **по префиксу** (подтверждено live:
  `"ABC-00012"` находится по `"ABC-000"`, но не по `"0012"`).

### Исправлено

- **`FormLinkValue.task_id`** — Pyrus возвращает и `task_id` (одиночный),
  и `task_ids`, но в модели был только список: одиночный ID терялся.
- **`ctx.get_value_id()`** для `form_link` теперь возвращает `int` для
  одиночной ссылки (раньше — всегда список).

Тесты: +21 (всего ~1074 passed).

---
## [0.9.2] — 2026-07-01

### Добавлено — поиск задач по ожидающему approver

- **`ApprovalPendingFilter(ids, any_step=True)`** — новый параметр.
  По умолчанию фильтр проверяет **только текущий шаг** задачи
  (`task.approvals[current_step - 1]`). С `any_step=True` ищет по
  **всем** шагам маршрута — approver может ждать согласования на
  любом шаге, даже если задача до него ещё не дошла.

  Это устраняет частую путаницу «фильтр не работает со списком ID»:
  сам список (OR по нескольким person/role ID) работал и раньше, но
  когда approver'ы распределены по разным шагам, дефолтная проверка
  только текущего шага находила лишь часть — теперь есть `any_step`.

- **`UserClient.find_pending_approvals(approver_ids, forms=, steps=, any_step=)`** —
  helper для поиска задач на согласовании **на уровне реестра**
  (без бота). Реестр не отдаёт `approvals`, поэтому helper делает
  two-step: `get_registers(forms)` → `get_tasks(...)` (обогащение) →
  фильтрация по approver, ожидающему согласования. `any_step`
  по умолчанию `True`.

Уточнения в docstring: `ApprovalPendingFilter` принимает person_id
**или** role_id; если согласование назначено на роль — передавать
`role_id`, а не person_id членов роли.

Тесты: +11 (всего ~1047 passed).

---
## [0.9.1] — 2026-06-25

### Добавлено — редактирование таблиц как DataFrame

Поле типа «таблица» теперь редактируется через удобный
DataFrame-подобный API — по **именам колонок**, без знания
`row_id`, `col_id` и форматов ячеек.

- **`await ctx.table("Имя")`** → :class:`TableProxy`. Открывает
  поле-таблицу. Кешируется в контексте: повторный вызов возвращает
  тот же объект с накопленными правками.

- **Чтение — как pandas**: `tbl.columns`, `len(tbl)`, `tbl[i]`,
  итерация `for row in tbl`, `row["Колонка"]`, `row.to_dict()`,
  `tbl.to_records()`. `print(tbl)` рисует красивую ASCII-таблицу.

- **Фильтрация — как SQLAlchemy**: `tbl.where(**{"Колонка": значение})`
  и `tbl.find(...)`. Для `str` — регистронезависимая подстрока,
  для `bool` / чисел — точное совпадение.

- **Правка — как Excel**: `row["Колонка"] = value` (ленивая),
  `row.update({...})`, `tbl.add(**{...})`, `row.delete()`,
  `tbl.remove(row)`, `tbl.clear()`.

- **Авторезолв значений в ячейках** — та же логика, что у `ctx.fill()`:
  имя человека → `person_id`, `True`/`False` → `"checked"`/`"unchecked"`,
  название варианта → `choice_id`, строка каталога → `item_id`,
  текст/число — как есть.

- **Ленивая отправка**: все правки таблиц уходят одним запросом
  при `ctx.answer()` / `ctx.approve()` / `ctx.finish()`, вместе с
  обычными `ctx.fill()`. `ctx.pending_count()` и `ctx.discard()`
  учитывают правки таблиц.

Новые публичные типы: `TableProxy`, `Row`, `Column`
(экспортируются из `aiopyrus`). Метод `TaskContext.table()`.

Особенность Pyrus: у непроставленной галочки API вообще не
присылает ячейку — при чтении такое значение трактуется как `False`
(подтверждено live).

Пример: [`examples/14_table_editing.py`](examples/14_table_editing.py).
Тесты: +19 (всего ~1032 passed).

Подтверждено живьём на on-premise (форма с таблицей «План работ»,
колонки text / person / checkmark): чтение, ASCII-рендер, резолв имён,
сборка payload на добавление/правку/удаление строк.

---
## [0.8.1] — 2026-06-01

### Добавлено — архив входящих вебхуков

- **`save_raw_webhook(base_dir, raw_body, payload_data, headers)`** —
  утилита, которая сохраняет один входящий вебхук на диск в layout
  «одна папка на задачу, много файлов в папке»::

      <base_dir>/<task_id>/<YYYYMMDD_HHMMSS_ffffff>_<seq>.json

  Каждый файл — самодостаточный envelope: `received_at`, `task_id`,
  `headers` (включая `X-Pyrus-Sig`, `X-Pyrus-Retry`), `body`
  (распарсенный JSON либо `_raw_text` при невалидном JSON).
  Функция **никогда не бросает** — архивирование не должно
  ломать обработку вебхуков. Дисковый I/O вынесен в worker-поток
  через `asyncio.to_thread`. Имена файлов лексикографически
  упорядочены по времени поступления (timestamp + monotonic
  счётчик), даже когда тысячи вебхуков приходят в одной
  микросекунде.

- **`create_app(..., save_webhooks_dir=)`** — новый параметр у
  фабрики aiohttp-приложения. Когда задан, **каждый** входящий
  вебхук (включая retry-доставки и невалидный JSON) архивируется
  в указанную директорию **до** парсинга и верификации подписи.

- **`Dispatcher.start_webhook(..., save_webhooks_dir=)`** — тот же
  параметр пробрасывается из вершины публичного API.

Use case: сбор реальных webhook-payload'ов с production для
последующего анализа — отладка фильтров, обратная инженерия
shape'а полей, аудит, регрессионное тестирование.

Тесты: +12 в `test_webhook_archive.py` (всего ~1012 passed).

### CI / CD

- **Проверка целостности wheel** перед публикацией в PyPI:
  после `python -m build` открываем wheel и убеждаемся, что
  все ключевые модули (`aiopyrus/bot/bot.py`, `aiopyrus/types/*`,
  `aiopyrus/py.typed` и др.) присутствуют. Защищает от класса
  багов, когда сборка теряет вложенные пакеты — в этом случае
  pipeline падает, и битый wheel не уезжает в PyPI.

- `[build-system] requires = ["hatchling>=1.21.0"]` — явная
  нижняя граница, чтобы поведение `packages = ["aiopyrus"]`
  оставалось предсказуемым на разных билд-окружениях.

---
## [0.8.0] — 2026-05-29

Большой релиз поддержки Pyrus 2026 (после апгрейда Datacenter
v1.22 → v1.23 → v1.24).  Доработано всё, что добавили в API за
2025–2026, плюс закрыты пробелы в покрытии Roles / Lists / Calendar.

### Добавлено — Knowledge Base API (v1.24, headline-фича 2026)
- `get_knowledge_base_structure(parent_topic_id=None, depth=None)` —
  иерархия БЗ (статьи + темы).
- `get_knowledge_base_item(item_id)` — статья или тема по строковому ID.
- `create_knowledge_base_item(title, type, parent_topic_id, body)` —
  создать статью/тему.  Тип = `"article"` (нужен `body` с Markdown)
  или `"topic"`.
- `update_knowledge_base_item(item_id, ...)` — обновить.  Перемещение
  в корень: `parent_topic_id=None, parent_topic_id_changed=True`.
- `delete_knowledge_base_item(item_id, delete_with_children=)` — удалить.
- `get_knowledge_base_permissions(item_id)` — разрешения (admin-gated).
- `update_knowledge_base_permissions(item_id, inherit, readers, editors)` —
  обновить разрешения (вход — `list[int]`, ответ — `list[Person]`).

ID элементов БЗ — **строки** (`"BxqPU8UrjlC"`), не числа.

Модели: `KnowledgeBaseStructure`, `KnowledgeBaseStructureNode`,
`KnowledgeBaseItem`, `KnowledgeBaseAttachment`, `KnowledgeBasePermissions`.

### Добавлено — Awards API (v1.22+)
- `get_award_threshold(award_id)` / `set_award_threshold(...)` — пороги
  выдачи и отзыва наград.
- `get_member_award_counter(member_id, award_id)` — текущий счётчик
  награды у сотрудника.
- `increment_member_award_counter(member_id, award_id)` — увеличить.
- `set_member_award_counter(member_id, award_id, value=)` — выставить
  явно. **Важно:** `value` передаётся как `?value=N` query-string, не
  JSON-тело (особенность Pyrus).

Модели: `AwardThreshold`, `MemberAwardCounter`.

Note: на новых сборках Pyrus (cloud / on-premise свежие) endpoint
есть, но требует Configuration manager прав.  На legacy on-premise
сборках вернёт 202 «No HTTP resource was found» — обычный
`PyrusAPIError` в этом случае.

### Добавлено — Telephony (интеграция с call-центром)
- `register_call(account_id, from_number, to_number, mappings=, ...)` —
  зарегистрировать звонок (`POST /integrations/call`).  Возвращает
  ID созданной/найденной задачи и ответственного.
- `attach_call_record(account_id, record_file, ...)` — прикрепить аудио
  к задаче звонка (`POST /integrations/attachcallrecord`).  Идентификация
  задачи: по `task_id` ИЛИ `external_id` ИЛИ паре номеров.

Модели: `TelephonyMappingCode` (enum), `CallMapping` (с автоматической
сериализацией `datetime → ISO-8601 Z`), `TelephonyPersonRef`,
`RegisterCallResponse`, `AttachCallRecordResponse`.

### Добавлено — расширение покрытия
- `get_role(role_id)` — одна роль по ID.
- `delete_role(role_id, task_receiver_id=)` — удалить роль; тело DELETE
  содержит `task_receiver_id` (особенность Pyrus).
- `get_list(list_id)` — один список задач по ID.
- `get_list_tasks(list_id, ...)` — REST-вариант (`GET /lists/{id}/tasks`),
  пара к существующему `get_task_list` (POST).  Pyrus иногда опускает
  ключ `tasks` при пустом списке — корректно возвращаем `[]`.
- `update_list(list_id, name, member_ids, manager_ids, ...)` — обновить
  метаданные списка.

### Изменено — `get_calendar()`
- Новые параметры: `start_date_utc` / `end_date_utc` (datetime ISO 8601)
  и `include_meetings` (`true` / `false`).
- Старые `from_date` / `to_date` (`YYYY-MM-DD`) остались deprecated
  alias'ами — бросают `DeprecationWarning` и маппятся в новые
  параметры (с полуночью UTC).
- `include_meetings` сериализуется как `"true"`/`"false"` (подтверждено
  live: Pyrus отверг `"y"`/`"n"` для этого параметра, хотя у других
  булевых параметров формат `"y"`/`"n"` работает).

Добавлена модель `Meeting` (`MeetingJoinParameters`) и
`CalendarResponse` (новый shape `{has_more, tasks, meetings}`).

### Добавлено — расширение `Person` (модель)
- `organization_id: int | None` — ID организации сотрудника.
- `birth_date: dict | None` — `{day, month, year?}`.
- `messenger: Messenger | None` — типизирован (`type`, `nickname`),
  вместо старого `dict[str, Any]`.
- Шесть полей политики admin-сессий (только на корп/on-premise):
  `mobile_session_settings`, `mobile_session_inactive_settings`,
  `mobile_session_restriction_settings`, `web_session_settings`,
  `web_session_inactive_settings`, `web_session_restriction_settings` —
  все типа `SessionPolicy | None`.

### Добавлено — `ChannelType.max`
- Константа MAX (VK мессенджер) — добавлен в Pyrus v1.23 (26.02.2026)
  как новый канал поддержки клиентов.

### Подтверждено живьём
- KB structure на on-premise — 82 items в корне, рекурсивная иерархия,
  строковые ID, корректно парсятся.
- `Roles` (37 тыс. ролей), `Lists` (1.2 тыс. списков) — все методы
  работают, включая роли с переносами в названии.
- Calendar новые параметры — задачи возвращаются.
- Awards — endpoint существует и на cloud, и на on-premise (403 без
  Configuration manager прав).
- KB на cloud — endpoint работает, в нашем тестовом workspace пусто.

Тесты: **36 новых** (всего ~1000 проходят).

---
## [0.7.3] — 2026-05-29

### Добавлено
- **`Channel.direction`** — поле направления внешнего канала
  (`"inbound"` / `"outbound"`). Подтверждено живьём на on-premise
  Pyrus 2026: бот-сгенерированные комментарии приходят с
  `channel.direction='outbound'`. Раньше silently dropped через
  `extra="ignore"`. Полезно ботам, которые должны игнорировать
  собственный исходящий трафик и реагировать только на входящие
  сообщения клиентов. Тип — свободный `str` для forward-compat,
  как и `Channel.type`.

### Документация
- В методы журнала событий (`get_event_history`,
  `get_file_access_history`, `get_task_access_history`,
  `get_task_export_history`, `get_registry_download_history`) добавлен
  блок `Raises`: `PyrusPermissionError` (`403 access_denied`) бросается,
  когда у аккаунта нет роли доступа к журналу безопасности. Нахождение
  на on-premise инстансе **не достаточно** — администратор должен выдать
  отдельную роль доступа к журналу. Это была самая частая жалоба
  «`aiopyrus` сломан».
- `Role.fired` / `Role.banned` помечены как **cloud-only** поля.
  On-premise инстансы не возвращают эти ключи; дефолт `False` не
  отражает реальное состояние роли там.
- `TaskStep` — добавлено замечание о том, что номера шагов
  могут быть **непоследовательными** при ветвлении маршрута
  (например, `steps=[1, 2, 4]` если шаг 3 был пропущен).

### Проверено
- aiopyrus 0.7.2 → 0.7.3 против Pyrus Datacenter on-premise
  (после апгрейда v1.22 → v1.23 → v1.24) — **ноль ошибок валидации**
  на 24 живых вызовах эндпоинтов; все 22 уникальных значения
  `FieldType` и все 22 ключа `Comment` парсятся корректно.
  Апгрейд 2026 для aiopyrus не-breaking.

---
## [0.7.2] — 2026-05-28

### Fixed
- **`Channel.type` no longer crashes `Task` parsing on unknown values.**
  Pyrus corp/on-premise instances send server-internal channel types not in
  the documented list — observed: `delay_escalation`. Previously a single
  such comment broke `Task.model_validate()` and made the task entirely
  unreadable (e.g. `get_task`, `task_context`, polling all failed). The
  field is now read into a plain `str`; the `ChannelType` enum stays as a
  set of constants for *sending* comments.
- **`find_member()` accepts numeric strings as person IDs.**
  `find_member("100500")` (typical when `person_id` is stored as `str` in
  a database / CSV) now performs a direct `GET /members/{id}` lookup
  instead of failing the name search. `find_member(int)` is also explicitly
  supported. Errors (404 / 403) return `None`. Knock-on fix: `ctx.reassign()`
  and `ctx.fill("Person field", "100500")` now also work with numeric strings.

### Added
- **`find_member_by_id(person_id)`** — strict, unambiguous lookup by `person_id`.
  Symmetric to `find_member_by_email` — accepts `int` or numeric `str`,
  returns `None` on 404 / 403 instead of raising. Useful when there are
  several namesakes in the org and the auto-resolver inside `find_member`
  would be ambiguous.

---
## [0.7.1] — 2026-04-26

### Fixed
- **Pyright errors in tests**: `FakeBot` mocks now cast to `PyrusBot` for
  `Filter.resolve()` calls — фикс CI после v0.7.0.

---
## [0.7.0] — 2026-04-26

### Added
- **`FormFilter` принимает названия форм**: `FormFilter("Заявки на доступ")` —
  имена резолвятся в `id` через `bot.get_forms()` один раз при старте
  диспетчера (polling/webhook). Поддерживает смешанный список:
  `FormFilter([321, "Согласование договора"])`. Совпадение точное,
  с case-insensitive fallback. Если имя не найдено — `ValueError` со
  списком доступных форм.
- **`Filter.resolve(bot)`**: новый async-хук базового класса для
  одноразовой инициализации фильтров. `AndFilter` / `OrFilter` /
  `NotFilter` рекурсивно проксируют вызов в дочерние фильтры.
- **`Router.resolve_filters(bot)` / `Dispatcher._ensure_filters_resolved`**:
  диспетчер автоматически вызывает `resolve` на всех зарегистрированных
  фильтрах при первом `start_polling` / `start_inbox_polling` /
  `process_webhook`. Идемпотентно — повторных вызовов API не делает.

---
## [0.6.1] — 2026-03-03

### Fixed
- **`__init__.py` missing from PyPI wheel**: `.gitignore` pattern `_*.py` was
  matched by hatchling's `pathspec` against `__init__.py`, excluding all 8
  `__init__.py` files from the built wheel. Result: `from aiopyrus import UserClient`
  failed on clean `pip install` (Python 3.10–3.14). Added `!__init__.py` negation rule.

---
## [0.6.0] — 2026-03-03

### Added
- **Catalog string resolution**: `ctx.fill("Тип запроса", "Программа / Веб-ресурс")`
  — строки для catalog-полей автоматически резолвятся в `item_id` через 6-проходный
  поиск (точный, по колонке, по частям, case-insensitive варианты)
- **`get_id(field_name)`**: получить числовой ID поля по имени из интерфейса
- **`get_type(field_name)`**: получить тип поля (`"text"`, `"catalog"`, `"multiple_choice"`, …)
- **`get_value_id(field_name)`**: получить ID текущего значения —
  `choice_id` для multiple_choice, `item_id` для catalog, `person_id` для person,
  `task_ids` для form_link
- **`get_catalog_id(field_name)`**: получить ID каталога из определения формы
- **`dump(field_name)`**: поле как dict (JSON); `dump()` без аргументов — вся задача
- **`find(pattern, default)`**: поиск поля по паттерну имени (`%описание%`)

### Changed
- **`set()` → `fill()`**: основной метод записи переименован в `fill()` —
  лучше отражает «заполнить поле формы». `set()` и `put()` работают как алиасы
- **Method aliases**: все getter-методы имеют синонимы —
  `field_id`=`get_id`, `field_type`=`get_type`, `value_id`=`get_value_id`,
  `catalog_id`=`get_catalog_id`
- **`__version__`**: автосинхронизация с `pyproject.toml` через `importlib.metadata`
  вместо хардкода

---
## [0.5.1] — 2026-03-01

### Changed
- **Default timeout**: 30s → 60s (рекомендация Pyrus для корпоративных инстансов)

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
