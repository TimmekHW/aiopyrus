"""07_middleware_errors.py — Middleware, обработка ошибок, продвинутые паттерны.
                           Middleware, error handling, advanced patterns.

Что показано / What is shown:
  - BaseMiddleware — как писать свои middleware
  - Цепочка middleware — порядок вызова
  - Middleware для логирования, тайминга, обработки ошибок
  - Глобальный обработчик ошибок через middleware
  - PyrusBot vs UserClient — взаимозаменяемость
  - Router nesting — вложенные роутеры

Middleware — обёртка вокруг каждого handler'а. Вызывается ДО и ПОСЛЕ handler'а.
Middleware is a wrapper around every handler. Called BEFORE and AFTER the handler.

Порядок middleware / Middleware order:
  dp.middleware(A)
  dp.middleware(B)
  # A.__call__ → B.__call__ → handler → B returns → A returns
"""

import asyncio
import logging
import time

from aiopyrus import Dispatcher, PyrusBot, TaskContext
from aiopyrus.bot.filters import FormFilter, StepFilter
from aiopyrus.bot.middleware import BaseMiddleware
from aiopyrus.bot.router import Router

# ── Настройки / Settings ─────────────────────────────────────────────────────

LOGIN = "bot@example.com"
SECURITY_KEY = "YOUR_SECURITY_KEY"
BASE_URL = "https://pyrus.mycompany.com"

FORM_ID = 321

# ── PyrusBot vs UserClient ───────────────────────────────────────────────────
#
# PyrusBot наследует UserClient. Единственное отличие — метод verify_signature
# для проверки подписи вебхуков. Для polling-режима разницы нет.
#
# PyrusBot extends UserClient. The only difference is verify_signature
# for webhook signature verification. For polling mode, they are identical.
#
# Оба варианта работают:
# bot = PyrusBot(login=LOGIN, security_key=KEY, base_url=URL)
# bot = UserClient(login=LOGIN, security_key=KEY, base_url=URL)
#
# Dispatcher принимает PyrusBot, но UserClient тоже подойдёт для polling.

bot = PyrusBot(
    login=LOGIN,
    security_key=SECURITY_KEY,
    base_url=BASE_URL,
)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("bot")


# ══════════════════════════════════════════════════════════════════════════════
# MIDDLEWARE
# ══════════════════════════════════════════════════════════════════════════════


# ── 1. Logging middleware ─────────────────────────────────────────────────────


class LoggingMiddleware(BaseMiddleware):
    """Логирует каждый вызов handler'а — task_id, время выполнения.

    Logs every handler call — task_id, execution time.
    """

    async def __call__(self, handler, payload, bot, data):
        t0 = time.perf_counter()
        log.info("[IN]  task_id=%d", payload.task_id)
        try:
            result = await handler(payload, bot, data)
            elapsed = (time.perf_counter() - t0) * 1000
            log.info("[OUT] task_id=%d  %.0fms", payload.task_id, elapsed)
            return result
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log.error("[ERR] task_id=%d  %.0fms  %s", payload.task_id, elapsed, e)
            raise


# ── 2. Error-catching middleware (глобальный обработчик ошибок) ────────────────


class ErrorCatchMiddleware(BaseMiddleware):
    """Ловит ВСЕ исключения в handler'ах и не даёт боту упасть.

    Catches ALL exceptions in handlers, preventing the bot from crashing.
    Optionally posts the error as a comment on the task.
    """

    def __init__(self, *, comment_errors: bool = False):
        self.comment_errors = comment_errors

    async def __call__(self, handler, payload, bot, data):
        try:
            return await handler(payload, bot, data)
        except Exception as e:
            log.exception("Handler error for task_id=%d: %s", payload.task_id, e)
            if self.comment_errors:
                import contextlib

                with contextlib.suppress(Exception):
                    await bot.comment_task(
                        payload.task_id,
                        text=f"[bot error] {type(e).__name__}: {e}",
                    )
            return None  # swallow the error, continue polling


# ── 3. Data-injection middleware ──────────────────────────────────────────────


class InjectMetadataMiddleware(BaseMiddleware):
    """Добавляет данные в data dict — доступны всем handler'ам через extra kwargs.

    Injects metadata into the data dict — available to all handlers via extra kwargs.

    Handler может принимать эти данные по имени:

        @dp.task_received()
        async def handle(ctx, start_time):  # start_time придёт из middleware
            ...
    """

    async def __call__(self, handler, payload, bot, data):
        data["start_time"] = time.time()
        data["bot_version"] = "1.0.0"
        return await handler(payload, bot, data)


# ── Регистрация middleware (порядок важен!) ──────────────────────────────────
# Первый зарегистрированный = самый внешний.
# ErrorCatch должен быть первым, чтобы ловить ошибки из всех остальных.

dp.middleware(ErrorCatchMiddleware(comment_errors=False))
dp.middleware(LoggingMiddleware())
dp.middleware(InjectMetadataMiddleware())

# Порядок вызова:
#   ErrorCatch → Logging → InjectMetadata → handler → InjectMetadata → Logging → ErrorCatch
#
# Если handler кинет исключение:
#   ErrorCatch → Logging → InjectMetadata → handler RAISES → Logging logs error → ErrorCatch catches


# ══════════════════════════════════════════════════════════════════════════════
# ROUTERS (вложенные роутеры / nested routers)
# ══════════════════════════════════════════════════════════════════════════════

# Роутеры позволяют разделить логику по файлам/модулям.
# Routers let you split logic across files/modules.

approval_router = Router(name="approvals")
notification_router = Router(name="notifications")


@approval_router.task_received(FormFilter(FORM_ID), StepFilter(2))
async def on_step_2(ctx: TaskContext):
    """Автосогласование на шаге 2."""
    await ctx.approve("Auto-approved by bot")


@notification_router.task_received(FormFilter(FORM_ID))
async def on_any_task(ctx: TaskContext):
    """Уведомление о любой задаче (fallback)."""
    log.info("Task %d changed, step=%s", ctx.id, ctx.step)


# Подключаем роутеры к диспетчеру
# Порядок важен: первый совпавший handler выигрывает
dp.include_router(approval_router)
dp.include_router(notification_router)


# ══════════════════════════════════════════════════════════════════════════════
# ЗАПУСК / START
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(
        dp.start_polling(
            bot,
            form_id=FORM_ID,
            interval=30,
            skip_old=True,
        )
    )
