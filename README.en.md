# aiopyrus

[![PyPI](https://img.shields.io/pypi/v/aiopyrus)](https://pypi.org/project/aiopyrus/)
[![Python](https://img.shields.io/pypi/pyversions/aiopyrus)](https://pypi.org/project/aiopyrus/)
[![CI](https://github.com/TimmekHW/aiopyrus/actions/workflows/ci.yml/badge.svg)](https://github.com/TimmekHW/aiopyrus/actions/workflows/ci.yml)
[![Downloads](https://static.pepy.tech/badge/aiopyrus/month)](https://pepy.tech/projects/aiopyrus)
[![License](https://img.shields.io/github/license/TimmekHW/aiopyrus)](LICENSE)

Async Python library for the [Pyrus API](https://pyrus.com/en/help/api).
Aiogram-style architecture. Powered by HTTPX.

> **[Русская версия](README.md)**

## Three Modes of Operation

### UserClient — async scripts under your own account

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

### SyncClient — simple scripts without async/await

Same functionality as `UserClient`, but without `async/await`.
For scripts, Jupyter notebooks, and simple integrations.

```python
from aiopyrus import SyncClient

with SyncClient(login="user@example.com", security_key="KEY") as client:
    profile = client.get_profile()
    print(f"Hello, {profile.first_name}!")

    ctx = client.task_context(12345678)
    print(ctx["Task Status"])
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
| `await ctx.answer("text", private=True)` | Private comment |
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

    # CSV export
    csv_text = await client.get_register_csv(321, steps=[1, 2])

    # Multiple form registers in parallel
    regs = await client.get_registers([321, 322, 323])
    for form_id, tasks in regs.items():
        print(f"Form {form_id}: {len(tasks)} tasks")

    # Stream large register (10 000+ tasks, no full load into memory)
    async for task in client.stream_register(321, steps=[1, 2]):
        print(task.id, task.current_step)

    # Parallel search across multiple forms
    all_tasks = await client.search_tasks({321: [1, 2], 322: None})

    # Task lists (projects / kanban boards)
    lists = await client.get_lists()
    list_tasks = await client.get_task_list(lists[0].id)

    # Catalogs
    catalogs = await client.get_catalogs()
    cat = await client.get_catalog(999)
    item = cat.find_item("Moscow")

    # Members
    person = await client.find_member("John Smith")
    members = await client.get_members()

    # Avatar
    uploaded = await client.upload_file("photo.jpg")
    await client.set_avatar(person.id, uploaded.guid)

    # Roles
    roles = await client.get_roles()

    # Files
    uploaded = await client.upload_file("/path/to/file.pdf")
    content = await client.download_file("guid")

    # Attach file to a comment
    await client.comment_task(task_id, text="Document", attachments=[uploaded.guid])

    # Attach file to a file-type field
    await client.comment_task(task_id, field_updates=[
        {"id": 686, "value": [{"guid": uploaded.guid}]},
    ])

    # Print forms (PDF)
    pdf = await client.download_print_form(task_id=12345678, print_form_id=1)

    # Announcements
    announcements = await client.get_announcements()
```

## Batch Operations

Parallel execution via `asyncio.gather`:

```python
async with UserClient(login=LOGIN, security_key=KEY) as client:
    # Fetch multiple tasks in parallel (errors are skipped)
    tasks = await client.get_tasks([1001, 1002, 1003])

    # Create multiple tasks (typed models)
    from aiopyrus import NewTask, NewRole, MemberUpdate
    results = await client.create_tasks([
        NewTask(form_id=321, fields=[{"id": 1, "value": "A"}]),
        NewTask(text="Simple task"),
    ])

    # Comment on multiple tasks via TaskContext
    ctxs = await client.task_contexts([1001, 1002])
    ctxs[0].set("Status", "Done")
    ctxs[1].set("Status", "Rejected")
    await asyncio.gather(
        ctxs[0].approve("Approved"),
        ctxs[1].reject("Rejected"),
    )

    # Multiple form registers in parallel
    regs = await client.get_registers([321, 322, 323])

    # Batch role and member operations
    await client.create_roles([NewRole(name="Admins", member_ids=[1, 2]), NewRole(name="Users")])
    await client.update_members([MemberUpdate(member_id=100, position="Lead"), MemberUpdate(member_id=200, position="Dev")])
```

## Utilities

### FieldUpdate — field update builder

```python
from aiopyrus import FieldUpdate

# Manual factories
updates = [
    FieldUpdate.text(field_id=1, value="Moscow"),
    FieldUpdate.choice(field_id=2, choice_id=3),
    FieldUpdate.person(field_id=3, person_id=100500),
    FieldUpdate.checkmark(field_id=4, checked=True),
    FieldUpdate.catalog(field_id=5, item_id=42),
]

# Auto-detect format by field type
task = await client.get_task(12345678)
updates = [
    FieldUpdate.from_field(task.get_field("Status"), 3),          # choice_id
    FieldUpdate.from_field(task.get_field("Assignee"), 100500),    # person_id
    FieldUpdate.from_field(task.get_field("Description"), "Text"), # text
]
await client.comment_task(task.id, field_updates=updates)
```

### URL Helpers

```python
# Browser link to a task
url = client.get_task_url(12345678)
# → "https://pyrus.com/t#id12345678"

# Browser link to a form
url = client.get_form_url(321)
# → "https://pyrus.com/form/321"
```

Works for on-premise too: `https://pyrus.mycompany.com/t#id12345678`.

### Other utilities

```python
from aiopyrus import get_flat_fields, format_mention, select_fields

# Recursive flatten of nested fields (title sections, tables)
flat = get_flat_fields(task.fields)

# HTML @mention for formatted_text fields
html = format_mention(100500, header="John Smith")
await client.comment_task(task_id, formatted_text=html)

# Client-side field projection from Pydantic models
tasks = await client.get_register(321)
slim = select_fields(tasks, {"id", "current_step", "fields"})
```

## Testing

```python
from aiopyrus import create_mock_client
from aiopyrus.types import Task

# AsyncMock with spec=UserClient
mock = create_mock_client(
    get_task=Task(id=12345678, text="Test"),
    get_members=[],
)

task = await mock.get_task(12345678)
assert task.id == 12345678
mock.get_task.assert_awaited_once_with(12345678)

# Async context manager support
async with mock as client:
    await client.get_inbox()
```

## Approval Step Management

```python
# Re-request approval (reset step to "waiting")
await client.comment_task(task_id, approvals_rerequested=[[141636]])

# Add approver to a step
await client.comment_task(task_id, approvals_added=[[{"id": 141636}]])

# Remove approver from a step
await client.comment_task(task_id, approvals_removed=[{"id": 141636}])
```

Pyrus bots combine `approvals_removed` + `approvals_added` to switch tasks between workflow steps.

## Event Log (on-premise)

Audit endpoints available only on Pyrus server (on-premise) instances. All return CSV.

```python
# Security event log (logins, password changes, roles — 113 event types)
csv = await client.get_event_history(after=1000, count=500)

# File access history
csv = await client.get_file_access_history(count=1000)

# Task access / task export / registry download history
csv = await client.get_task_access_history()
csv = await client.get_task_export_history()
csv = await client.get_registry_download_history()
```

Details: https://pyrus.com/ru/help/api/event-log

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
    ssl_verify=False,  # self-signed certificates
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

See [`examples/`](examples/) — 12 files from simple to advanced:

| File | Topic |
|---|---|
| [`01_quickstart.py`](examples/01_quickstart.py) | Connection, profile, inbox, TaskContext |
| [`02_task_context.py`](examples/02_task_context.py) | All read/write methods, approval, time tracking |
| [`03_bot_webhook.py`](examples/03_bot_webhook.py) | Webhook bot, routers, filters, middleware |
| [`04_bot_polling.py`](examples/04_bot_polling.py) | Polling mode, skip_old, lifecycle hooks |
| [`05_data_management.py`](examples/05_data_management.py) | Registers, catalogs, members, roles, files |
| [`06_approval_bot.py`](examples/06_approval_bot.py) | Approval monitoring bot, `enrich`, inbox polling |
| [`07_middleware_errors.py`](examples/07_middleware_errors.py) | Middleware, error handling, nested routers |
| [`08_inbox_vs_register.py`](examples/08_inbox_vs_register.py) | Inbox vs Register: choosing the right approach |
| [`09_auto_processing.py`](examples/09_auto_processing.py) | UserClient: task processing by link |
| [`10_polling_auto_approve.py`](examples/10_polling_auto_approve.py) | Polling + FormFilter + StepFilter + ApprovalPendingFilter |
| [`11_http_integration.py`](examples/11_http_integration.py) | HTTP server for external systems (PHP, 1C, etc.) |
| [`12_embed_in_project.py`](examples/12_embed_in_project.py) | Embedding aiopyrus into FastAPI / Django / Celery |

## FAQ

### How does aiopyrus differ from the official pyrus-api?

[pyrus-api](https://pypi.org/project/pyrus-api/) is a synchronous wrapper by Pyrus built on `requests`. aiopyrus is a fully async framework on `httpx` with a router/filter/middleware system inspired by aiogram. Fields are accessed by their UI names, not by `field_id`.

### Do I need a public server to run a bot?

No. There is a polling mode (`dp.start_polling(...)`) — the bot polls Pyrus on a timer. Works behind firewalls, NAT, VPN.

### Are on-premise Pyrus installations supported?

Yes. Pass `base_url` when creating the client:

```python
client = UserClient(
    login="user@corp.com",
    security_key="KEY",
    base_url="https://pyrus.mycompany.com",
    ssl_verify=False,  # for self-signed certificates
)
```

### Can I use it without a bot, just as an API client?

Yes, that's exactly what `UserClient` is for — scripts under your own account, no bot registration needed.

## License

MIT
