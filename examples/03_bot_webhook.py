"""03_bot_webhook.py — Бот на вебхуках / Webhook bot.

Полная структура production-ready бота на aiopyrus.
Complete structure of a production-ready aiopyrus bot.

Что показано / What is shown:
  - PyrusBot + Dispatcher + Router — базовая структура
  - @router.task_received(*filters) — регистрация обработчиков
  - FormFilter, StepFilter, TextFilter, FieldValueFilter — встроенные фильтры
  - F.form_id == ..., F.text.contains(...) — Magic F фильтры
  - Композиция фильтров: &, |, ~
  - BaseMiddleware — логирование и error-handling
  - dp.include_router() — разбивка на модули
  - dp.start_webhook() — запуск сервера

Запуск / How to run:
  python examples/03_bot_webhook.py

  Потом настройте URL вебхука в Pyrus:
  Then configure the webhook URL in Pyrus:
    Настройки -> Боты -> ваш бот -> URL: https://your-host.example.com:8080/pyrus
"""

import asyncio
import contextlib
import logging

from aiopyrus import (
    BaseMiddleware,
    Dispatcher,
    EventFilter,
    F,
    FieldValueFilter,
    FormFilter,
    PyrusBot,
    Router,
    StepFilter,
)
from aiopyrus.types.webhook import WebhookPayload
from aiopyrus.utils.context import TaskContext

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ── Учётные данные / Credentials ─────────────────────────────────────────────
BOT_LOGIN = "bot@example"
SECURITY_KEY = "YOUR_BOT_SECURITY_KEY"

# ── ID форм и шагов (замените на свои) / Form and step IDs (replace) ─────────
FORM_INVOICE = 321  # форма "Счета на оплату" / "Invoices" form
FORM_SUPPORT = 322  # форма "IT-заявки" / "IT requests" form
STEP_APPROVE = 2  # шаг "Согласование" / "Approval" step
STEP_EXECUTE = 3  # шаг "Исполнение" / "Execution" step


# =============================================================================
# Middleware — выполняется вокруг каждого обработчика
# Middleware — runs around every handler
# =============================================================================


class LoggingMiddleware(BaseMiddleware):
    """Логирует каждый входящий вебхук / Logs every incoming webhook."""

    async def __call__(self, handler, payload: WebhookPayload, bot, data: dict):
        log.info("[IN]  task_id=%-10d  event=%s", payload.task_id, payload.event)
        try:
            result = await handler(payload, bot, data)
            log.info("[OUT] task_id=%-10d  ok", payload.task_id)
            return result
        except Exception as exc:
            log.exception("[ERR] task_id=%d: %s", payload.task_id, exc)
            return None


class ErrorNotifierMiddleware(BaseMiddleware):
    """Перехватывает ошибки и оставляет комментарий в задаче.
    Catches errors and posts a comment in the task."""

    async def __call__(self, handler, payload: WebhookPayload, bot, data: dict):
        try:
            return await handler(payload, bot, data)
        except ValueError as exc:
            log.error("Handler error (task %d): %s", payload.task_id, exc)
            with contextlib.suppress(Exception):
                await bot.comment_task(payload.task_id, text=f"[Ошибка бота] {exc}")
            return None


# =============================================================================
# Роутер для счетов / Router for invoices
# =============================================================================

invoice_router = Router(name="invoices")


@invoice_router.task_received(FormFilter(FORM_INVOICE), StepFilter(STEP_APPROVE))
async def on_invoice_approval(ctx: TaskContext) -> None:
    """Автоматическое согласование счетов до 100 000.
    Auto-approve invoices up to 100 000."""
    amount_str = ctx.get("Сумма", "0")
    try:
        amount = float(str(amount_str).replace(",", ".").replace(" ", ""))
    except (ValueError, AttributeError):
        amount = 0.0

    log.info("Invoice task_id=%d amount=%.2f", ctx.id, amount)

    if amount <= 100_000:
        ctx.set("Статус", "Одобрено")
        await ctx.approve(f"Сумма {amount_str} в пределах лимита. Одобрено автоматически.")
    else:
        # Превышение — передать на ручное рассмотрение
        # Over limit — escalate for manual review
        await ctx.reassign(
            "Данил Колбасенко",
            f"Сумма {amount_str} превышает лимит автоматического согласования.",
        )


# =============================================================================
# Роутер для IT-заявок / Router for IT support
# =============================================================================

support_router = Router(name="support")


# Фильтр по значению поля — FieldValueFilter
# Filter by field value — FieldValueFilter
@support_router.task_received(
    FormFilter(FORM_SUPPORT),
    StepFilter(STEP_EXECUTE),
    FieldValueFilter(field_name="Тип проблемы", value="Проблема с доступом"),
)
async def on_access_issue(ctx: TaskContext) -> None:
    """Заявки на доступ — назначить ответственного автоматически.
    Access requests — auto-assign responsible."""
    ctx.set("Ответственный", "Данил Колбасенко")
    ctx.set("Статус", "В работе")
    await ctx.answer("Заявка принята. Назначен ответственный.")


# Комбинация фильтров через & (AND) — все должны совпасть
# Filter composition via & (AND) — all must match
@support_router.task_received(
    FormFilter(FORM_SUPPORT)
    & StepFilter(STEP_EXECUTE)
    & FieldValueFilter(field_name="Тип проблемы", value="Плановые работы"),
)
async def on_scheduled_work(ctx: TaskContext) -> None:
    """Плановые работы — подтвердить. Planned work — confirm."""
    ctx.set("Статус", "Согласовано")
    await ctx.approve("Плановые работы согласованы.")


# =============================================================================
# Magic F фильтры (альтернативный компактный стиль)
# Magic F filters (alternative concise style)
# =============================================================================

urgent_router = Router(name="urgent")


# F.text.contains() — поиск по тексту задачи (case-insensitive)
# F.form_id.in_()   — задача принадлежит одной из форм
@urgent_router.task_received(
    F.form_id.in_([FORM_INVOICE, FORM_SUPPORT]),
    F.text.contains("срочно"),
)
async def on_urgent(ctx: TaskContext) -> None:
    """Задачи с пометкой "срочно" — приоритизировать.
    Tasks marked "urgent" — prioritize."""
    ctx.set("Приоритет", "Срочный")
    await ctx.answer("Отмечено как срочное. Ответственный уведомлён.")


# EventFilter — только определённые типы событий
# EventFilter — only specific event types
@urgent_router.task_received(
    EventFilter("task_created"),
    FormFilter(FORM_SUPPORT),
)
async def on_new_support_task(ctx: TaskContext) -> None:
    """Приветствие при создании новой заявки.
    Welcome message on new request."""
    requester = ctx.task.author.full_name if ctx.task.author else "коллега"
    await ctx.answer(f"Привет, {requester}! Заявка принята. Ожидайте ответа в течение 4 часов.")


# =============================================================================
# Сборка и запуск / Assembly and launch
# =============================================================================

bot = PyrusBot(login=BOT_LOGIN, security_key=SECURITY_KEY)
dp = Dispatcher()

# Middleware (порядок: первый зарегистрированный = первый выполняется)
# Middleware (order: first registered = first executed)
dp.middleware(LoggingMiddleware())
dp.middleware(ErrorNotifierMiddleware())

# Роутеры (порядок важен — первый совпавший обработчик выполняется)
# Routers (order matters — first matching handler runs)
dp.include_router(urgent_router)  # проверяется первым / checked first
dp.include_router(invoice_router)
dp.include_router(support_router)

if __name__ == "__main__":
    asyncio.run(
        dp.start_webhook(
            bot,
            host="0.0.0.0",
            port=8080,
            path="/pyrus",
            verify_signature=True,  # проверять X-Pyrus-Sig / verify X-Pyrus-Sig header
        )
    )
