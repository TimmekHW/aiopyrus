"""04_bot_polling.py — Бот без публичного сервера: режим опроса (polling).
                      Bot without a public server: polling mode.

Polling — альтернатива вебхукам. Бот сам опрашивает реестр формы каждые N секунд.
Работает за любым файрволом, не требует публичного URL.

Polling is an alternative to webhooks. The bot polls the form register every N seconds.
Works behind any firewall, requires no public URL.

Обработчики (@router.task_received) — такие же, как в webhook-режиме.
Handlers (@router.task_received) are the same as in webhook mode.

Что показано / What is shown:
  - dp.start_polling() — запуск без сервера
  - skip_old=True   — не обрабатывать существующие задачи при старте
  - skip_old=False   — обработать весь бэклог при старте
  - on_startup / on_shutdown — хуки жизненного цикла
  - ModifiedAfterFilter — per-handler защита от повторной обработки
  - Настройка rate limiting — не превысить лимиты API
"""

import asyncio
import logging

from aiopyrus import (
    Dispatcher,
    FieldValueFilter,
    FormFilter,
    PyrusBot,
    Router,
    StepFilter,
)
from aiopyrus.bot.filters import ModifiedAfterFilter
from aiopyrus.utils.context import TaskContext

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ── Учётные данные / Credentials ─────────────────────────────────────────────
BOT_LOGIN = "bot@example"
SECURITY_KEY = "YOUR_BOT_SECURITY_KEY"

FORM_ID = 321  # Форма которую опрашиваем / Form to poll
POLL_STEP = 2  # Шаг / Step


# ── Обработчики / Handlers ───────────────────────────────────────────────────

router = Router(name="main")


# ВАЖНО: polling отслеживает last_modified_date. Если хендлер изменяет задачу
# (ctx.set, ctx.answer), она появится в следующем poll как «изменённая» и хендлер
# сработает повторно. FieldValueFilter(value=None) ниже — защита от этого:
# после первого прогона поле «Статус» уже не пустое → фильтр отсекает задачу.
#
# IMPORTANT: polling tracks last_modified_date. If a handler modifies the task
# (ctx.set, ctx.answer), the next poll re-dispatches it. FieldValueFilter(value=None)
# below guards against this: after the first run "Статус" is no longer empty.
#
# ModifiedAfterFilter() — дополнительная защита: только задачи, изменённые после
# старта бота. Полезно при skip_old=False.
# ModifiedAfterFilter() — extra safety: only tasks modified after bot start.
@router.task_received(
    FormFilter(FORM_ID),
    StepFilter(POLL_STEP),
    ModifiedAfterFilter(),  # только свежие / only fresh
    FieldValueFilter(field_name="Статус", value=None),  # поле пустое / field is empty
)
async def on_unprocessed(ctx: TaskContext) -> None:
    """Задачи на нужном шаге с незаполненным статусом — обработать."""
    log.info("Processing task %d (step=%d)", ctx.id, ctx.step)
    ctx.set("Статус", "В обработке")
    await ctx.answer("Бот принял задачу в работу.")


@router.task_received(FormFilter(FORM_ID), StepFilter(POLL_STEP))
async def on_fallback(ctx: TaskContext) -> None:
    """Fallback — все остальные задачи на этом шаге (уже обработанные).
    Fallback — all other tasks on this step (already processed)."""
    log.debug("Fallback handler for task %d", ctx.id)


# ── Хуки жизненного цикла / Lifecycle hooks ──────────────────────────────────


async def on_startup() -> None:
    log.info("Бот запущен. Опрашиваем форму %d, шаг %d", FORM_ID, POLL_STEP)
    log.info("Bot started. Polling form %d, step %d", FORM_ID, POLL_STEP)


async def on_shutdown() -> None:
    log.info("Бот остановлен. / Bot stopped.")


# ── Сборка / Assembly ────────────────────────────────────────────────────────

bot = PyrusBot(
    login=BOT_LOGIN,
    security_key=SECURITY_KEY,
    # Rate limiting — важно при polling, чтобы не превысить лимиты API
    # Rate limiting — important for polling to stay within API limits
    requests_per_minute=30,  # не более 30 запросов в минуту / max 30 req/min
    requests_per_10min=4000,  # с запасом от лимита 5000 / buffer below 5000 limit
)

dp = Dispatcher()
dp.include_router(router)

if __name__ == "__main__":
    asyncio.run(
        dp.start_polling(
            bot,
            form_id=FORM_ID,
            steps=POLL_STEP,  # фильтр на уровне реестра / register-level filter
            interval=30.0,  # секунды между запросами / seconds between polls
            skip_old=True,  # True = snapshot при старте, False = обработать бэклог
            # True = snapshot on start, False = process backlog
            on_startup=on_startup,
            on_shutdown=on_shutdown,
        )
    )
