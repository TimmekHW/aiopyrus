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

## Данные организации

```python
async with UserClient(login=LOGIN, security_key=KEY) as client:
    # Реестр с фильтрами
    tasks = await client.get_register(321, steps=[1, 2], due_filter="overdue")

    # Параллельный поиск по нескольким формам
    all_tasks = await client.search_tasks({321: [1, 2], 322: None})

    # Каталоги
    catalogs = await client.get_catalogs()
    cat = await client.get_catalog(999)
    item = cat.find_item("Москва")

    # Участники
    person = await client.find_member("Данил Колбасенко")
    members = await client.get_members()

    # Роли
    roles = await client.get_roles()

    # Файлы
    uploaded = await client.upload_file("/path/to/file.pdf")
    content = await client.download_file("guid")

    # Объявления
    announcements = await client.get_announcements()
```

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

В папке [`examples/`](examples/) — 7 файлов от простого к сложному:

| Файл | Тема |
|---|---|
| [`01_quickstart.py`](examples/01_quickstart.py) | Подключение, профиль, inbox, TaskContext |
| [`02_task_context.py`](examples/02_task_context.py) | Все методы чтения/записи, согласование, трекинг |
| [`03_bot_webhook.py`](examples/03_bot_webhook.py) | Бот на вебхуках, роутеры, фильтры, middleware |
| [`04_bot_polling.py`](examples/04_bot_polling.py) | Polling-режим, skip_old, lifecycle hooks |
| [`05_data_management.py`](examples/05_data_management.py) | Реестры, каталоги, участники, роли, файлы |
| [`06_approval_bot.py`](examples/06_approval_bot.py) | Бот-наблюдатель за согласованиями, `enrich`, inbox polling |
| [`07_middleware_errors.py`](examples/07_middleware_errors.py) | Middleware, обработка ошибок, вложенные роутеры |

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
