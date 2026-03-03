"""aiopyrus — Async Pyrus API library, aiogram-style, HTTPX-powered.

Work with Pyrus tasks using **human-readable field names** (exactly as shown in
the Pyrus UI) without knowing field IDs, choice_id values, or person_id numbers.

Работайте с задачами Pyrus через **имена полей**, как в интерфейсе —
без знания ID, choice_id или person_id.

Quick start / Быстрый старт
----------------------------

**Async client / Асинхронный клиент**::

    import asyncio
    from aiopyrus import UserClient

    async def main():
        async with UserClient(login="user@example.com", security_key="KEY") as client:
            ctx = await client.task_context(12345678)
            status = ctx["Статус задачи"]   # → "Открыта"
            ctx.fill("Статус задачи", "В работе")
            await ctx.answer("Принято в работу")

    asyncio.run(main())

**Sync client — scripts & notebooks / Скрипты и ноутбуки**::

    from aiopyrus import SyncClient

    with SyncClient(login="user@example.com", security_key="KEY") as client:
        ctx = client.task_context(12345678)
        print(ctx["Статус задачи"])

**Bot — webhook-driven, aiogram-style / Вебхук-бот**::

    import asyncio
    from aiopyrus import PyrusBot, Dispatcher, Router
    from aiopyrus.bot import FormFilter, StepFilter
    from aiopyrus.utils.context import TaskContext

    bot = PyrusBot(login="bot@example", security_key="SECRET")
    dp  = Dispatcher()
    router = Router()

    @router.task_received(FormFilter(321), StepFilter(1))
    async def on_invoice(ctx: TaskContext):
        amount = float(ctx["Сумма"])
        if amount > 100_000:
            await ctx.reject("Сумма превышает лимит — отклонено.")
        else:
            ctx.fill("Статус задачи", "Одобрено")
            await ctx.approve("Одобрено автоматически.")

    dp.include_router(router)

    asyncio.run(dp.start_webhook(bot, host="0.0.0.0", port=8080, path="/pyrus"))


TaskContext — method reference / Справочник методов
----------------------------------------------------

Full docs: ``aiopyrus.utils.context`` (module docstring).

+--------------------------------------------+-----------------------------------------------+
| Method / Метод                             | Description / Описание                        |
+============================================+===============================================+
| ``ctx["Field"]``                           | Read field value (human-readable)              |
+--------------------------------------------+-----------------------------------------------+
| ``ctx.get("Field", default)``              | Read with default / с дефолтом                 |
+--------------------------------------------+-----------------------------------------------+
| ``ctx.find("%pattern%", default)``         | Fuzzy find by name / поиск по имени            |
+--------------------------------------------+-----------------------------------------------+
| ``ctx.raw("Field")``                       | Raw FormField pydantic object                  |
+--------------------------------------------+-----------------------------------------------+
| ``ctx.dump("Field")``                      | Field as dict (JSON) / поле как dict           |
+--------------------------------------------+-----------------------------------------------+
| ``ctx.dump()``                             | Entire task as dict / задача как dict           |
+--------------------------------------------+-----------------------------------------------+
| ``ctx.fill("Field", value)``               | Schedule write (lazy) / ленивая запись          |
+--------------------------------------------+-----------------------------------------------+
| aliases: ``set()`` / ``put()``             | Same as fill() / то же что fill()              |
+--------------------------------------------+-----------------------------------------------+
| ``ctx.discard()``                          | Drop uncommitted fill()-s                      |
+--------------------------------------------+-----------------------------------------------+
| ``ctx.get_id("Field")``                    | Field ID / числовой ID поля                    |
+--------------------------------------------+-----------------------------------------------+
| ``ctx.get_type("Field")``                  | Field type / тип поля (text, catalog, …)       |
+--------------------------------------------+-----------------------------------------------+
| ``ctx.get_value_id("Field")``              | Value ID (choice_id / item_id / person_id)     |
+--------------------------------------------+-----------------------------------------------+
| ``await ctx.get_catalog_id("Field")``      | Catalog ID from form / ID каталога              |
+--------------------------------------------+-----------------------------------------------+
| ``await ctx.answer("text")``               | Comment + flush all pending writes              |
+--------------------------------------------+-----------------------------------------------+
| ``await ctx.approve("text")``              | Approve approval step / утвердить               |
+--------------------------------------------+-----------------------------------------------+
| ``await ctx.reject("text")``               | Reject approval step / отклонить                |
+--------------------------------------------+-----------------------------------------------+
| ``await ctx.finish("text")``               | Finish the task / завершить задачу              |
+--------------------------------------------+-----------------------------------------------+
| ``await ctx.reassign("Name")``             | Reassign (string → person_id auto)              |
+--------------------------------------------+-----------------------------------------------+
| ``await ctx.log_time(min)``                | Log time spent / трекинг времени                |
+--------------------------------------------+-----------------------------------------------+
| ``await ctx.reply(id, "text")``            | Reply to a comment / ответить                   |
+--------------------------------------------+-----------------------------------------------+
"""

from .bot.bot import PyrusBot
from .bot.dispatcher import Dispatcher
from .bot.filters import (
    ApprovalPendingFilter,
    EventFilter,
    F,
    FieldValueFilter,
    FormFilter,
    ResponsibleFilter,
    StepFilter,
    TextFilter,
)
from .bot.middleware import BaseMiddleware
from .bot.router import Router
from .exceptions import (
    PyrusAPIError,
    PyrusAuthError,
    PyrusError,
    PyrusFileSizeError,
    PyrusNotFoundError,
    PyrusPermissionError,
    PyrusRateLimitError,
    PyrusWebhookSignatureError,
)
from .sync import SyncClient
from .testing import create_mock_client
from .types import (
    Announcement,
    ApprovalChoice,
    ApprovalEntry,
    Attachment,
    BotResponse,
    Catalog,
    CatalogFieldValue,
    CatalogItem,
    CatalogSyncResult,
    Channel,
    ChannelContact,
    ChannelType,
    Comment,
    CommentChannel,
    ContactsResponse,
    Form,
    FormField,
    FormLinkValue,
    InboxResponse,
    MemberUpdate,
    MultipleChoiceValue,
    NewRole,
    NewTask,
    Person,
    PersonRef,
    PrintFormItem,
    Profile,
    RegisterResponse,
    Role,
    RoleUpdate,
    SubscriberEntry,
    TableRow,
    Task,
    TaskList,
    TaskStep,
    TitleValue,
    UploadedFile,
    WebhookPayload,
)
from .user.client import UserClient
from .utils.context import TaskContext
from .utils.fields import FieldUpdate, format_mention, get_flat_fields, select_fields

try:
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("aiopyrus")
except Exception:  # noqa: BLE001
    __version__ = "0.0.0"
_CODENAME = "Перезрелая груша с кривым API"  # 🍐
__all__ = [
    # Clients & context
    "UserClient",
    "SyncClient",
    "TaskContext",
    "PyrusBot",
    # Bot infrastructure
    "Dispatcher",
    "Router",
    "BaseMiddleware",
    # Filters
    "F",
    "FormFilter",
    "StepFilter",
    "ResponsibleFilter",
    "TextFilter",
    "EventFilter",
    "FieldValueFilter",
    "ApprovalPendingFilter",
    # Types
    "Task",
    "TaskList",
    "TaskStep",
    "Comment",
    "ApprovalChoice",
    "ApprovalEntry",
    "SubscriberEntry",
    "Channel",
    "ChannelType",
    "ChannelContact",
    "CommentChannel",
    "Form",
    "FormField",
    "CatalogFieldValue",
    "MultipleChoiceValue",
    "TitleValue",
    "FormLinkValue",
    "TableRow",
    "Person",
    "Role",
    "Profile",
    "Catalog",
    "CatalogItem",
    "CatalogSyncResult",
    "Attachment",
    "UploadedFile",
    "ContactsResponse",
    "InboxResponse",
    "RegisterResponse",
    "Announcement",
    "WebhookPayload",
    "BotResponse",
    # Request params & type aliases
    "PersonRef",
    "NewTask",
    "NewRole",
    "RoleUpdate",
    "MemberUpdate",
    "PrintFormItem",
    # Utilities
    "FieldUpdate",
    "get_flat_fields",
    "format_mention",
    "select_fields",
    # Testing
    "create_mock_client",
    # Exceptions
    "PyrusError",
    "PyrusAPIError",
    "PyrusAuthError",
    "PyrusNotFoundError",
    "PyrusPermissionError",
    "PyrusRateLimitError",
    "PyrusFileSizeError",
    "PyrusWebhookSignatureError",
]
