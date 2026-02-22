# aiopyrus

[![PyPI](https://img.shields.io/pypi/v/aiopyrus)](https://pypi.org/project/aiopyrus/)
[![Python](https://img.shields.io/pypi/pyversions/aiopyrus)](https://pypi.org/project/aiopyrus/)
[![CI](https://github.com/TimmekHW/aiopyrus/actions/workflows/ci.yml/badge.svg)](https://github.com/TimmekHW/aiopyrus/actions/workflows/ci.yml)
[![Downloads](https://img.shields.io/pypi/dm/aiopyrus)](https://pypi.org/project/aiopyrus/)
[![License](https://img.shields.io/github/license/TimmekHW/aiopyrus)](LICENSE)

Async Python library for the [Pyrus API](https://pyrus.com/en/help/api).
Aiogram-style architecture. Powered by HTTPX.

> **[Русская версия](README.md)**

## Two Modes of Operation

### UserClient — scripts under your own account

Task automation, data exports, bulk operations — **under your own Pyrus account**.
No bot registration needed, no public server required.

```python
import asyncio
from aiopyrus import UserClient

async def main():
    async with UserClient(login="user@example.com", security_key="KEY") as client:
        profile = await client.get_profile()
        print(f"Hello, {profile.first_name}!")

        ctx = await client.task_context(12345678)
        print(ctx.get("Task Status", "not set"))

asyncio.run(main())
```

### PyrusBot — webhook / polling bot

Incoming task processing, automatic approvals, routing — aiogram-style.

```python
bot = PyrusBot(login="bot@example", security_key="SECRET")
dp = Dispatcher()
```

> More about bots — [below](#webhook-bot).

---

## How to Get Your security_key

1. In Pyrus, click **Settings** (gear icon, bottom left)
2. Go to **Authorization** ([pyrus.com/t#authorize](https://pyrus.com/t#authorize))
3. Copy the **Secret API Key**

Now you can run scripts under your own account:

```python
client = UserClient(login="you@company.com", security_key="<your key>")
```

---

## Key Feature — TaskContext

Work with tasks using **field names as they appear in the Pyrus UI** — no `field_id`, `choice_id`, or `person_id` needed.

```python
ctx = await client.task_context(12345678)

status   = ctx["Task Status"]           # multiple_choice → str
executor = ctx["Assignee"]              # person → "First Last"

ctx.set("Task Status", "In Progress")   # choice name → choice_id automatically
ctx.set("Assignee", "John Smith")       # name → person_id automatically
await ctx.answer("Accepted")
```

## Installation

```bash
pip install aiopyrus
```

Python 3.10+

## TaskContext — Method Reference

| Method | Description |
|---|---|
| `ctx["Field"]` | Read (KeyError if missing) |
| `ctx.get("Field", default)` | Read with default |
| `ctx.raw("Field")` | Raw `FormField` object |
| `ctx.find("%pattern%")` | Wildcard search (SQL LIKE style) |
| `ctx.set("Field", value)` | Lazy write (chainable) |
| `ctx.discard()` | Cancel pending `set()` calls |
| `ctx.pending_count()` | Number of pending `set()` calls |
| `await ctx.answer("text")` | Comment + flush all `set()` calls |
| `await ctx.approve("text")` | Approve an approval step |
| `await ctx.reject("text")` | Reject an approval step |
| `await ctx.finish("text")` | Finish (close) the task |
| `await ctx.reassign("Name")` | Reassign (name → person_id auto) |
| `await ctx.log_time(90, "text")` | Log time spent (minutes) |
| `await ctx.reply(comment_id, "text")` | Reply to a comment (threaded) |

## Webhook Bot

```python
import asyncio
from aiopyrus import PyrusBot, Dispatcher, Router, FormFilter, StepFilter
from aiopyrus.utils.context import TaskContext

bot = PyrusBot(login="bot@example", security_key="SECRET")
dp = Dispatcher()
router = Router()

@router.task_received(FormFilter(321), StepFilter(2))
async def on_invoice(ctx: TaskContext):
    amount = float(ctx.get("Amount", "0"))
    if amount > 100_000:
        await ctx.reject("Amount exceeds limit.")
    else:
        ctx.set("Status", "Approved")
        await ctx.approve("Auto-approved.")

dp.include_router(router)
asyncio.run(dp.start_webhook(bot, host="0.0.0.0", port=8080, path="/pyrus"))
```

## Polling Bot (no public server needed)

```python
asyncio.run(
    dp.start_polling(
        bot,
        form_id=321,
        steps=2,
        interval=30.0,       # seconds between polls
        skip_old=True,        # skip existing tasks on startup
    )
)
```

Works behind firewalls, no public URL required.

## Filters

```python
from aiopyrus import FormFilter, StepFilter, FieldValueFilter, EventFilter, F

# Classic
@router.task_received(FormFilter(321), StepFilter(2))

# By field value
@router.task_received(FieldValueFilter(field_name="Type", value="Bug"))

# Magic F
@router.task_received(F.form_id.in_([321, 322]), F.text.contains("urgent"))

# Composition: &, |, ~
@router.task_received(FormFilter(321) & StepFilter(2) & ~FieldValueFilter(field_name="Status", value="Closed"))

# Time-based (useful for polling)
from aiopyrus.bot.filters import ModifiedAfterFilter, CreatedAfterFilter
@router.task_received(ModifiedAfterFilter())  # only tasks modified after bot start
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

## Organization Data

```python
async with UserClient(login=LOGIN, security_key=KEY) as client:
    # Register with filters
    tasks = await client.get_register(321, steps=[1, 2], due_filter="overdue")

    # Parallel search across multiple forms
    all_tasks = await client.search_tasks({321: [1, 2], 322: None})

    # Catalogs
    catalogs = await client.get_catalogs()
    cat = await client.get_catalog(999)
    item = cat.find_item("Moscow")

    # Members
    person = await client.find_member("John Smith")
    members = await client.get_members()

    # Roles
    roles = await client.get_roles()

    # Files
    uploaded = await client.upload_file("/path/to/file.pdf")
    content = await client.download_file("guid")

    # Announcements
    announcements = await client.get_announcements()
```

## Rate Limiting

```python
bot = PyrusBot(
    login="bot@example",
    security_key="SECRET",
    requests_per_minute=30,
    requests_per_10min=4000,
)
```

Built-in rate limiter with exponential backoff. Pyrus API limits: 5000 requests / 10 min.

## On-premise

```python
client = UserClient(
    login="user@corp.com",
    security_key="KEY",
    base_url="https://pyrus.mycompany.com",
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

## Examples

See [`examples/`](examples/) — 5 files from simple to advanced:

| File | Topic |
|---|---|
| [`01_quickstart.py`](examples/01_quickstart.py) | Connection, profile, inbox, TaskContext |
| [`02_task_context.py`](examples/02_task_context.py) | All read/write methods, approval, time tracking |
| [`03_bot_webhook.py`](examples/03_bot_webhook.py) | Webhook bot, routers, filters, middleware |
| [`04_bot_polling.py`](examples/04_bot_polling.py) | Polling mode, skip_old, lifecycle hooks |
| [`05_data_management.py`](examples/05_data_management.py) | Registers, catalogs, members, roles, files |

## FAQ

### How does aiopyrus differ from the official pyrus-api?

[pyrus-api](https://pypi.org/project/pyrus-api/) is a synchronous wrapper by Pyrus built on `requests`. aiopyrus is a fully async framework on `httpx` with a router/filter/middleware system inspired by aiogram. Fields are accessed by their UI names, not by `field_id`.

### Do I need a public server to run a bot?

No. There is a polling mode (`dp.start_polling(...)`) — the bot polls Pyrus on a timer. Works behind firewalls, NAT, VPN.

### Are on-premise Pyrus installations supported?

Yes. Pass `base_url="https://pyrus.mycompany.com"` when creating the client.

### Can I use it without a bot, just as an API client?

Yes, that's exactly what `UserClient` is for — scripts under your own account, no bot registration needed.

## License

MIT
