# aiopyrus

[![PyPI](https://img.shields.io/pypi/v/aiopyrus)](https://pypi.org/project/aiopyrus/)
[![Python](https://img.shields.io/pypi/pyversions/aiopyrus)](https://pypi.org/project/aiopyrus/)
[![CI](https://github.com/TimmekHW/aiopyrus/actions/workflows/ci.yml/badge.svg)](https://github.com/TimmekHW/aiopyrus/actions/workflows/ci.yml)
[![Downloads](https://static.pepy.tech/badge/aiopyrus/month)](https://pepy.tech/projects/aiopyrus)
[![License](https://img.shields.io/github/license/TimmekHW/aiopyrus)](LICENSE)

Асинхронная Python-библиотека для [Pyrus API](https://pyrus.com/ru/help/api).
Стиль — как у aiogram. Под капотом — HTTPX.

> **[English version](README.en.md)**

## Два режима работы

### UserClient — скрипты от своего имени

Автоматизация задач, выгрузки, массовые операции — **от имени вашего аккаунта Pyrus**.
Не нужно регистрировать бота, не нужен публичный сервер.

```python
import asyncio
from aiopyrus import UserClient

async def main():
    async with UserClient(login="user@example.com", security_key="KEY") as client:
        profile = await client.get_profile()
        print(f"Привет, {profile.first_name}!")

        ctx = await client.task_context(12345678)
        print(ctx.get("Статус задачи", "не задан"))

asyncio.run(main())
```

### PyrusBot — бот на вебхуках / polling

Обработка входящих задач, автоматическое согласование, роутинг — aiogram-style.

```python
bot = PyrusBot(login="bot@example", security_key="SECRET")
dp = Dispatcher()
```

> Подробнее о ботах — [ниже](#бот-на-вебхуках).

---

## Где взять security_key

1. В Pyrus нажмите **Настройки** (шестерёнка слева внизу)
2. Перейдите в **Авторизация** ([pyrus.com/t#authorize](https://pyrus.com/t#authorize))
3. Скопируйте **Секретный API ключ**

Теперь можно запускать скрипты от своего имени:

```python
client = UserClient(login="you@company.com", security_key="<скопированный ключ>")
```

---

## Главная фишка — TaskContext

Работайте с задачами **по именам полей из интерфейса Pyrus** — без знания `field_id`, `choice_id`, `person_id`.

```python
ctx = await client.task_context(12345678)

status   = ctx["Статус задачи"]        # multiple_choice → str
executor = ctx["Исполнитель"]           # person → "Имя Фамилия"

ctx.set("Статус задачи", "В работе")    # имя варианта → choice_id автоматически
ctx.set("Исполнитель", "Данил Колбасенко")  # имя → person_id автоматически
await ctx.answer("Принято в работу")
```

## Установка

```bash
pip install aiopyrus
```

Python 3.10+

## TaskContext — справочник методов

| Метод | Описание |
|---|---|
| `ctx["Поле"]` | Чтение (KeyError если нет) |
| `ctx.get("Поле", default)` | Чтение с дефолтом |
| `ctx.raw("Поле")` | Сырой `FormField` объект |
| `ctx.find("%паттерн%")` | Поиск по wildcard (как SQL LIKE) |
| `ctx.set("Поле", value)` | Ленивая запись (чейнится) |
| `ctx.discard()` | Отмена накопленных `set()` |
| `ctx.pending_count()` | Сколько `set()` ждут отправки |
| `await ctx.answer("текст")` | Комментарий + сброс всех `set()` |
| `await ctx.answer("текст", private=True)` | Приватный комментарий |
| `await ctx.approve("текст")` | Утвердить шаг согласования |
| `await ctx.reject("текст")` | Отклонить шаг согласования |
| `await ctx.finish("текст")` | Завершить задачу |
| `await ctx.reassign("Имя")` | Переназначить (имя → person_id) |
| `await ctx.log_time(90, "текст")` | Списать время (минуты) |
| `await ctx.reply(comment_id, "текст")` | Ответить на комментарий (тред) |

## Бот на вебхуках

```python
import asyncio
from aiopyrus import PyrusBot, Dispatcher, Router, FormFilter, StepFilter
from aiopyrus.utils.context import TaskContext

bot = PyrusBot(login="bot@example", security_key="SECRET")
dp = Dispatcher()
router = Router()

@router.task_received(FormFilter(321), StepFilter(2))
async def on_invoice(ctx: TaskContext):
    amount = float(ctx.get("Сумма", "0"))
    if amount > 100_000:
        await ctx.reject("Сумма превышает лимит.")
    else:
        ctx.set("Статус", "Одобрено")
        await ctx.approve("Одобрено автоматически.")

dp.include_router(router)
asyncio.run(dp.start_webhook(bot, host="0.0.0.0", port=8080, path="/pyrus"))
```

## Бот на polling (без публичного сервера)

```python
asyncio.run(
    dp.start_polling(
        bot,
        form_id=321,
        steps=2,
        interval=30.0,       # секунды между запросами
        skip_old=True,        # не обрабатывать существующие задачи
    )
)
```

Работает за файрволом, не требует публичный URL.

## Фильтры

```python
from aiopyrus import FormFilter, StepFilter, FieldValueFilter, EventFilter, F

# Классические
@router.task_received(FormFilter(321), StepFilter(2))

# По значению поля
@router.task_received(FieldValueFilter(field_name="Тип", value="Баг"))

# Magic F
@router.task_received(F.form_id.in_([321, 322]), F.text.contains("срочно"))

# Композиция: &, |, ~
@router.task_received(FormFilter(321) & StepFilter(2) & ~FieldValueFilter(field_name="Статус", value="Закрыт"))

# Временные (для polling)
from aiopyrus.bot.filters import ModifiedAfterFilter, CreatedAfterFilter
@router.task_received(ModifiedAfterFilter())  # только задачи, изменённые после старта бота
```

## Middleware

```python
from aiopyrus import BaseMiddleware

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, payload, bot, data):
        print(f"Task {payload.task_id}")
        return await handler(payload, bot, data)

dp.middleware(LoggingMiddleware())
```

## Inbox vs Register vs get_task — что возвращает API

Разные эндпоинты Pyrus возвращают **разный объём данных** в задаче:

| Поле | `GET /inbox` | `GET /register` | `GET /tasks/{id}` |
|---|:---:|:---:|:---:|
| `id`, `text`, `author`, даты | + | + | + |
| `current_step` | - | + | + |
| `fields` | - | + | + |
| `form_id` | - | - | + |
| `approvals` | - | - | + |
| `comments` | - | - | + |

**Что это значит для фильтрации:**

- `FormFilter` и `StepFilter` **не сработают** на данных из inbox (всё `None`).
- `start_polling(form_id=...)` автоматически подставляет `form_id` — фильтры работают.
- Для inbox-поллинга нужен `enrich=True` (дополнительный `get_task()` на каждую задачу).

**Рекомендация:** если знаете формы — используйте `start_polling(form_id=[id1, id2])`.
Inbox-поллинг подходит только для сценария «все входящие без фильтрации».

## Данные организации

```python
async with UserClient(login=LOGIN, security_key=KEY) as client:
    # Реестр с фильтрами
    tasks = await client.get_register(321, steps=[1, 2], due_filter="overdue")

    # CSV-экспорт реестра
    csv_text = await client.get_register_csv(321, steps=[1, 2])

    # Параллельный поиск по нескольким формам
    all_tasks = await client.search_tasks({321: [1, 2], 322: None})

    # Списки задач (проекты / канбан-доски)
    lists = await client.get_lists()
    list_tasks = await client.get_task_list(lists[0].id)

    # Каталоги
    catalogs = await client.get_catalogs()
    cat = await client.get_catalog(999)
    item = cat.find_item("Москва")

    # Участники
    person = await client.find_member("Данил Колбасенко")
    members = await client.get_members()

    # Аватар
    uploaded = await client.upload_file("photo.jpg")
    await client.set_avatar(person.id, uploaded.guid)

    # Роли
    roles = await client.get_roles()

    # Файлы
    uploaded = await client.upload_file("/path/to/file.pdf")
    content = await client.download_file("guid")

    # Прикрепить файл к комментарию
    await client.comment_task(task_id, text="Документ", attachments=[uploaded.guid])

    # Прикрепить файл к полю типа file
    await client.comment_task(task_id, field_updates=[
        {"id": 686, "value": [{"guid": uploaded.guid}]},
    ])

    # Печатные формы (PDF)
    pdf = await client.download_print_form(task_id=12345678, print_form_id=1)

    # Объявления
    announcements = await client.get_announcements()
```

## Батч-операции

Параллельное выполнение через `asyncio.gather`:

```python
async with UserClient(login=LOGIN, security_key=KEY) as client:
    # Получить несколько задач параллельно (ошибки пропускаются)
    tasks = await client.get_tasks([1001, 1002, 1003])

    # Создать несколько задач (типизированные модели)
    from aiopyrus import NewTask, NewRole, MemberUpdate
    results = await client.create_tasks([
        NewTask(form_id=321, fields=[{"id": 1, "value": "A"}]),
        NewTask(text="Простая задача"),
    ])

    # Прокомментировать несколько задач через TaskContext
    ctxs = await client.task_contexts([1001, 1002])
    ctxs[0].set("Статус", "Выполнена")
    ctxs[1].set("Статус", "Отклонена")
    await asyncio.gather(
        ctxs[0].approve("Одобрено"),
        ctxs[1].reject("Отклонено"),
    )

    # Батч-операции с ролями и участниками
    await client.create_roles([NewRole(name="Admins", member_ids=[1, 2]), NewRole(name="Users")])
    await client.update_members([MemberUpdate(member_id=100, position="Lead"), MemberUpdate(member_id=200, position="Dev")])
```

## Утилиты

### FieldUpdate — конструктор обновлений полей

```python
from aiopyrus import FieldUpdate

# Ручные фабрики
updates = [
    FieldUpdate.text(field_id=1, value="Москва"),
    FieldUpdate.choice(field_id=2, choice_id=3),
    FieldUpdate.person(field_id=3, person_id=100500),
    FieldUpdate.checkmark(field_id=4, checked=True),
    FieldUpdate.catalog(field_id=5, item_id=42),
]

# Автоопределение формата по типу поля
task = await client.get_task(12345678)
updates = [
    FieldUpdate.from_field(task.get_field("Статус"), 3),            # choice_id
    FieldUpdate.from_field(task.get_field("Исполнитель"), 100500),   # person_id
    FieldUpdate.from_field(task.get_field("Описание"), "Текст"),     # text
]
await client.comment_task(task.id, field_updates=updates)
```

### Прочие утилиты

```python
from aiopyrus import get_flat_fields, format_mention, select_fields

# Рекурсивный flatten вложенных полей (title-секции, таблицы)
flat = get_flat_fields(task.fields)

# HTML @упоминание для formatted_text
html = format_mention(100500, header="Данил Колбасенко")
await client.comment_task(task_id, formatted_text=html)

# Выборка полей из списка моделей
tasks = await client.get_register(321)
slim = select_fields(tasks, {"id", "current_step", "fields"})
```

## Тестирование

```python
from aiopyrus import create_mock_client
from aiopyrus.types import Task

# AsyncMock с spec=UserClient
mock = create_mock_client(
    get_task=Task(id=12345678, text="Test"),
    get_members=[],
)

task = await mock.get_task(12345678)
assert task.id == 12345678
mock.get_task.assert_awaited_once_with(12345678)

# Поддержка async context manager
async with mock as client:
    await client.get_inbox()
```

## Управление этапами согласования

```python
# Пересогласование (вернуть шаг в «ожидание»)
await client.comment_task(task_id, approvals_rerequested=[[141636]])

# Добавить согласующего на этап
await client.comment_task(task_id, approvals_added=[[{"id": 141636}]])

# Убрать согласующего с этапа
await client.comment_task(task_id, approvals_removed=[{"id": 141636}])
```

Боты Pyrus комбинируют `approvals_removed` + `approvals_added` для переключения задачи между этапами.

## Rate limiting

```python
bot = PyrusBot(
    login="bot@example",
    security_key="SECRET",
    requests_per_minute=30,
    requests_per_10min=4000,
)
```

Встроенный rate limiter с экспоненциальным backoff. Лимиты Pyrus API: 5000 запросов / 10 мин.

## On-premise

```python
client = UserClient(
    login="user@corp.ru",
    security_key="KEY",
    base_url="https://pyrus.mycompany.ru",
    ssl_verify=False,  # самоподписанные сертификаты
)
```

## Proxy

```python
client = UserClient(
    login="user@example.com",
    security_key="KEY",
    proxy="http://proxy.corp:8080",
)
```

## Примеры

В папке [`examples/`](examples/) — 12 файлов от простого к сложному:

| Файл | Тема |
|---|---|
| [`01_quickstart.py`](examples/01_quickstart.py) | Подключение, профиль, inbox, TaskContext |
| [`02_task_context.py`](examples/02_task_context.py) | Все методы чтения/записи, согласование, трекинг |
| [`03_bot_webhook.py`](examples/03_bot_webhook.py) | Бот на вебхуках, роутеры, фильтры, middleware |
| [`04_bot_polling.py`](examples/04_bot_polling.py) | Polling-режим, skip_old, lifecycle hooks |
| [`05_data_management.py`](examples/05_data_management.py) | Реестры, каталоги, участники, роли, файлы |
| [`06_approval_bot.py`](examples/06_approval_bot.py) | Бот-наблюдатель за согласованиями, `enrich`, inbox polling |
| [`07_middleware_errors.py`](examples/07_middleware_errors.py) | Middleware, обработка ошибок, вложенные роутеры |
| [`08_inbox_vs_register.py`](examples/08_inbox_vs_register.py) | Inbox vs Register: что выбрать, мульти-форм polling |
| [`09_auto_processing.py`](examples/09_auto_processing.py) | UserClient: обработка задачи по ссылке |
| [`10_polling_auto_approve.py`](examples/10_polling_auto_approve.py) | Polling + FormFilter + StepFilter + ApprovalPendingFilter |
| [`11_http_integration.py`](examples/11_http_integration.py) | HTTP-сервер для внешних систем (PHP, 1C и др.) |
| [`12_embed_in_project.py`](examples/12_embed_in_project.py) | Встраивание aiopyrus в FastAPI / Django / Celery |

## FAQ

### Чем aiopyrus отличается от официального pyrus-api?

[pyrus-api](https://pypi.org/project/pyrus-api/) — синхронная обёртка от Pyrus на `requests`. aiopyrus — полностью асинхронный фреймворк на `httpx` с системой роутеров, фильтров и middleware как в aiogram. Работа с полями задач идёт по именам из интерфейса, а не по `field_id`.

### Нужен ли публичный сервер для бота?

Нет. Есть polling-режим (`dp.start_polling(...)`) — бот сам опрашивает Pyrus по таймеру. Работает за файрволом, NAT, VPN.

### Поддерживаются ли on-premise инсталляции Pyrus?

Да. Передайте `base_url` при создании клиента:

```python
client = UserClient(
    login="user@corp.ru",
    security_key="KEY",
    base_url="https://pyrus.mycompany.ru",
    ssl_verify=False,  # для самоподписанных сертификатов
)
```

### Можно ли использовать без бота, просто как API-клиент?

Да, именно для этого есть `UserClient` — скрипты от имени вашего аккаунта без регистрации бота.

## Лицензия

MIT
