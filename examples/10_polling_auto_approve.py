"""10_polling_auto_approve.py — Polling + фильтры + автосогласование.
                                Polling + filters + auto-approval.

Сценарий / Scenario:
  UserClient следит за формой 228, шаг 2, ожидание согласования от person_id=67.
  Когда задача попадает под фильтры:
    1. Вытаскиваем «Описание» и «ФИО»
    2. Статус «Открыта» → «В работе», исполнитель «Тестов Тест Тестович»
    3. Отправляем данные во внешний микросервис
    4. Получаем ответ
    5. Статус «В работе» → «Выполнено»
    6. Списываем 5 минут
    7. Делаем апрув

  UserClient watches form 228, step 2, pending approval from person_id=67.
  When a task matches the filters, it runs the full processing cycle.
"""

import asyncio
import logging

from aiopyrus import Dispatcher, PyrusBot, TaskContext
from aiopyrus.bot.filters import ApprovalPendingFilter, FormFilter, StepFilter

# ── Настройки / Settings ─────────────────────────────────────────────────────

LOGIN = "user@example.com"
SECURITY_KEY = "YOUR_SECURITY_KEY"

FORM_ID = 228
STEP = 2
APPROVER_ID = 67  # person_id того, чьё согласование ждём

# ── Бот и диспетчер / Bot & dispatcher ───────────────────────────────────────

bot = PyrusBot(login=LOGIN, security_key=SECURITY_KEY)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)


# ── Условный микросервис / Mock microservice ─────────────────────────────────


async def call_external_service(description: str, fio: str) -> dict:
    """Имитация вызова внешнего API.
    Simulates an external API call.
    """
    print(f"  -> Микросервис: описание={description[:60]}..., ФИО={fio}")
    await asyncio.sleep(0.5)
    return {"status": "ok", "ticket": "INC-42"}


# ── Обработчик / Handler ────────────────────────────────────────────────────


@dp.task_received(
    FormFilter(FORM_ID),
    StepFilter(STEP),
    ApprovalPendingFilter(APPROVER_ID),
)
async def on_approval_needed(ctx: TaskContext):
    """Задача на форме 228, шаг 2, ждёт согласования от person 67.
    Task on form 228, step 2, pending approval from person 67.
    """
    print(f"\n{'=' * 60}")
    print(f"Новая задача: #{ctx.id} | step={ctx.step}")

    # 1. Вытаскиваем поля / Extract fields
    description = ctx.get("Описание", "нет описания")
    fio = ctx.get("ФИО", "не указано")
    print(f"Описание: {description}")
    print(f"ФИО: {fio}")

    # 2. Статус → «В работе», исполнитель
    ctx.set("Статус", "В работе")
    ctx.set("Исполнитель", "Тестов Тест Тестович")
    await ctx.answer("Задача принята в работу автоматически")
    print("-> Статус: В работе")

    # 3. Внешний сервис / External service
    result = await call_external_service(str(description), str(fio))
    print(f"-> Ответ микросервиса: {result}")

    # 4. Статус → «Выполнено»
    ctx.set("Статус", "Выполнено")
    await ctx.answer(f"Обработано. Тикет: {result.get('ticket', 'N/A')}")
    print("-> Статус: Выполнено")

    # 5. Списываем 5 минут / Log 5 minutes
    await ctx.log_time(5, "Автоматическая обработка")
    print("-> Списано 5 минут")

    # 6. Апрув / Approve
    await ctx.approve("Согласовано автоматически")
    print("-> Задача согласована")


@dp.task_received()
async def on_other(ctx: TaskContext):
    """Все остальные задачи — пропускаем."""
    pass


# ── Запуск / Start ───────────────────────────────────────────────────────────


async def on_startup():
    print(f"Bot started: form={FORM_ID}, step={STEP}, approver={APPROVER_ID}")


async def on_shutdown():
    print("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(
        dp.start_polling(
            bot,
            form_id=FORM_ID,
            steps=STEP,
            interval=30,
            skip_old=False,
            enrich=True,  # обязательно для ApprovalPendingFilter
            on_startup=on_startup,
            on_shutdown=on_shutdown,
        )
    )
