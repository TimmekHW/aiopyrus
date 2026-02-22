"""aiopyrus — Async Pyrus API library, aiogram-style, HTTPX-powered.

Work with Pyrus tasks using **human-readable field names** (exactly as shown in
the Pyrus UI) without knowing field IDs, choice_id values, or person_id numbers.

Работайте с задачами Pyrus через **имена полей**, как в интерфейсе —
без знания ID, choice_id или person_id.

Quick start / Быстрый старт
----------------------------

**User client — one-shot automation / Разовые операции**::

    import asyncio
    from aiopyrus import UserClient

    async def main():
        async with UserClient(login="user@example.com", security_key="KEY") as client:
            ctx = await client.task_context(12345678)

            # Read fields by name (as shown in the Pyrus UI)
            # Читаем поля по имени из интерфейса
            status   = ctx["Статус задачи"]   # → "Открыта"  /  "Open"
            executor = ctx["Исполнитель"]      # → "Иванов Иван"

            # Lazy write + send / Запись (ленивая) + отправка
            ctx.set("Статус задачи", "В работе").set("Исполнитель", "ivanov")
            await ctx.answer("Задача принята в работу")  # or any text

            # Time tracking / Трекинг времени
            await ctx.log_time(60, "Incident analysis")

            # Reassign / Переназначить
            await ctx.reassign("Иванов Иван", "Passing this to you")

            # Reply to a comment / Ответить на комментарий
            first = ctx.task.comments[0]
            await ctx.reply(first.id, "Please clarify the details")

            # Finish / Завершить
            ctx.set("Статус задачи", "Выполнена")
            await ctx.approve("Processing complete")

    asyncio.run(main())


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
            ctx.set("Статус задачи", "Одобрено")
            await ctx.approve("Одобрено автоматически.")

    dp.include_router(router)

    asyncio.run(dp.start_webhook(bot, host="0.0.0.0", port=8080, path="/pyrus"))


TaskContext — method reference / Справочник методов
----------------------------------------------------

Full docs: ``aiopyrus.utils.context`` (module docstring).

+-----------------------------------+---------------------------------------+
| Method / Метод                    | Description / Описание                |
+===================================+=======================================+
| ``ctx["Field"]``                  | Read field value (human-readable)     |
+-----------------------------------+---------------------------------------+
| ``ctx.get("Field", default)``     | Read with default / с дефолтом        |
+-----------------------------------+---------------------------------------+
| ``ctx.set("Field", value)``       | Schedule write (lazy) / ленивая       |
+-----------------------------------+---------------------------------------+
| ``ctx.discard()``                 | Drop uncommitted set()-s              |
+-----------------------------------+---------------------------------------+
| ``await ctx.answer("text")``      | Comment + flush all set()-s           |
+-----------------------------------+---------------------------------------+
| ``await ctx.approve("text")``     | Approve approval step / утвердить     |
+-----------------------------------+---------------------------------------+
| ``await ctx.reject("text")``      | Reject approval step / отклонить      |
+-----------------------------------+---------------------------------------+
| ``await ctx.finish("text")``      | Finish the task / завершить задачу    |
+-----------------------------------+---------------------------------------+
| ``await ctx.reassign("Name")``    | Reassign (string → person_id auto)    |
+-----------------------------------+---------------------------------------+
| ``await ctx.log_time(min)``       | Log time spent / трекинг времени      |
+-----------------------------------+---------------------------------------+
| ``await ctx.reply(id, "text")``   | Reply to a comment / ответить         |
+-----------------------------------+---------------------------------------+
"""

from .bot.bot import PyrusBot
from .bot.dispatcher import Dispatcher
from .bot.filters import (
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
    PyrusNotFoundError,
    PyrusPermissionError,
    PyrusRateLimitError,
    PyrusWebhookSignatureError,
)
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
    MultipleChoiceValue,
    Person,
    Profile,
    RegisterResponse,
    Role,
    SubscriberEntry,
    TableRow,
    Task,
    TitleValue,
    UploadedFile,
    WebhookPayload,
)
from .user.client import UserClient
from .utils.context import TaskContext

__version__ = "0.1.1"
_CODENAME = "Перезрелая груша с кривым API"  # 🍐
__all__ = [
    # Clients & context
    "UserClient",
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
    # Types
    "Task",
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
    # Exceptions
    "PyrusError",
    "PyrusAPIError",
    "PyrusAuthError",
    "PyrusNotFoundError",
    "PyrusPermissionError",
    "PyrusRateLimitError",
    "PyrusWebhookSignatureError",
]
