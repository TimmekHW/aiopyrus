"""06_approval_bot.py — Бот-наблюдатель за согласованиями.
                       Approval monitoring bot.

Сценарий / Scenario:
  Бот следит за задачами, где определённая роль стоит на согласовании.
  Когда задача попадает на согласование этой роли — бот получает уведомление.

  The bot monitors tasks where a specific role is pending approval.
  When a task reaches that role's approval step — the bot fires a handler.

Два режима / Two modes:
  1. start_polling(form_id=...)     — опрос реестра конкретной формы
     Быстрее, но нужно знать form_id.
  2. start_inbox_polling()          — опрос входящих (inbox)
     Работает по всем формам, но видит только задачи из inbox пользователя.

Важно / Important:
  get_register() не возвращает approvals — только базовые поля.
  Для проверки согласований бот автоматически подгружает полную задачу
  через get_task() когда используется ApprovalPendingFilter.
"""

import asyncio
import logging

from aiopyrus import Dispatcher, PyrusBot, TaskContext
from aiopyrus.bot.filters import ApprovalPendingFilter, FormFilter

# ── Настройки / Settings ─────────────────────────────────────────────────────

LOGIN = "bot@example.com"
SECURITY_KEY = "YOUR_SECURITY_KEY"
BASE_URL = "https://pyrus.mycompany.com"  # on-premise

FORM_ID = 321  # ID формы / Form ID
ROLE_ID = 5555  # ID роли на согласовании / Approval role ID
FIELD_FIO = "ФИО сотрудника"

# ── Бот и диспетчер / Bot & dispatcher ────────────────────────────────────────

bot = PyrusBot(
    login=LOGIN,
    security_key=SECURITY_KEY,
    base_url=BASE_URL,
)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)


# ── Вариант 1: Polling реестра формы ──────────────────────────────────────────
# Для каждой задачи из реестра подгружаем полные данные через get_task,
# потому что get_register не возвращает approvals.


@dp.task_received(FormFilter(FORM_ID), ApprovalPendingFilter(ROLE_ID))
async def on_approval_needed(ctx: TaskContext):
    """Задача ждёт согласования от нашей роли."""
    fio = ctx.get(FIELD_FIO, "не указано")
    print(f"[APPROVAL] Task #{ctx.id} | {fio} | step={ctx.step}")

    # Автосогласование:
    # await ctx.approve("Согласовано автоматически")

    # Или просто уведомление:
    # await ctx.answer("Бот увидел задачу на согласовании")


@dp.task_received()
async def on_any_task(ctx: TaskContext):
    """Все остальные задачи (не на согласовании у нашей роли)."""
    pass  # молча пропускаем


async def on_startup():
    print(f"Bot started. Monitoring form {FORM_ID}, role {ROLE_ID}")


async def on_shutdown():
    print("Bot stopped.")


# ── Запуск / Start ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Вариант 1: Polling конкретной формы (рекомендуется)
    asyncio.run(
        dp.start_polling(
            bot,
            form_id=FORM_ID,
            interval=30,  # опрос каждые 30 сек
            skip_old=False,  # обработать все текущие задачи при старте
            enrich=True,  # подгрузить approvals через get_task
            on_startup=on_startup,
            on_shutdown=on_shutdown,
        )
    )

    # Вариант 2: Polling входящих (все формы)
    # NB: inbox API НЕ возвращает form_id, current_step, fields, approvals.
    #     enrich=True ОБЯЗАТЕЛЕН — иначе фильтры не сработают.
    #     Но это +1 запрос get_task() на каждую задачу в inbox.
    # NB: inbox API does NOT return form_id, current_step, fields, approvals.
    #     enrich=True is REQUIRED — otherwise filters won't work.
    #     But that's +1 get_task() request per every inbox task.
    # asyncio.run(
    #     dp.start_inbox_polling(
    #         bot,
    #         enrich=True,  # обязательно! / required!
    #         interval=60,
    #         skip_old=True,
    #         on_startup=on_startup,
    #         on_shutdown=on_shutdown,
    #     )
    # )

    # Вариант 3: Несколько форм одновременно
    # asyncio.run(
    #     dp.start_polling(
    #         bot,
    #         form_id=[321, 123456, 789012],
    #         interval=30,
    #         skip_old=False,
    #     )
    # )
