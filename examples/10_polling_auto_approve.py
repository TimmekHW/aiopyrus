"""10_polling_auto_approve.py — Polling + фильтры + автосогласование.
                                Polling + filters + auto-approval.

Сценарий / Scenario:
  Бот следит за формой 228, шаг 2, ожидание согласования от person_id=67.
  Когда задача попадает под фильтры:
    1. Вытаскиваем «Описание» и «ФИО»
    2. Отправляем данные во внешний микросервис
    3. Статус «Открыта» → «Выполнено», исполнитель, списываем время, апрув

  Bot watches form 228, step 2, pending approval from person_id=67.
  When a task matches the filters, it runs the full processing cycle.

ВАЖНО / IMPORTANT:
  FieldValueFilter(field_name="Статус", value="Открыта") — защита от повторного
  срабатывания. Polling отслеживает last_modified_date: если хендлер изменяет
  задачу (ctx.set, ctx.answer), следующий poll вызовет хендлер снова.
  FieldValueFilter отсекает задачу после первого прогона, т.к. статус уже не «Открыта».

  FieldValueFilter guards against self-triggering. Polling tracks last_modified_date:
  if a handler modifies the task, the next poll re-dispatches it. The filter
  rejects the task after the first run because the status is no longer "Открыта".
"""

import asyncio
import logging

from aiopyrus import Dispatcher, FieldValueFilter, PyrusBot, TaskContext
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
    FieldValueFilter(field_name="Статус", value="Открыта"),  # защита от повторного срабатывания
)
async def on_approval_needed(ctx: TaskContext):
    """Задача на форме 228, шаг 2, ждёт согласования от person 67, статус «Открыта».
    Task on form 228, step 2, pending approval from person 67, status "Открыта".
    """
    print(f"\n{'=' * 60}")
    print(f"Новая задача: #{ctx.id} | step={ctx.step}")

    # 1. Вытаскиваем поля / Extract fields
    description = ctx.get("Описание", "нет описания")
    fio = ctx.get("ФИО", "не указано")
    print(f"  Описание: {description}")
    print(f"  ФИО: {fio}")

    # 2. Внешний сервис / External service
    result = await call_external_service(str(description), str(fio))
    print(f"  -> Ответ микросервиса: {result}")

    # 3. Статус → «В работе», исполнитель, комментарий (1 API-вызов)
    ctx.set("Статус", "В работе")
    ctx.set("Исполнитель", "Тестов Тест Тестович")
    await ctx.answer(f"Обработано. Тикет: {result.get('ticket', 'N/A')}")
    print("  -> Статус: В работе")

    # 4. Статус → «Выполнено», списание времени, апрув (1 API-вызов)
    ctx.set("Статус", "Выполнено")
    await ctx.approve("Согласовано автоматически", duration=5)
    print("  -> Согласовано, списано 5 минут")


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
