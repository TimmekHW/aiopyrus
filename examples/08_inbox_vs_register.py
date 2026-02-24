"""08_inbox_vs_register.py — Inbox vs Register: что выбрать для фильтрации.
                             Inbox vs Register: which one to use for filtering.

TL;DR:
  - GET /inbox возвращает ТОЛЬКО: id, author, responsible, text, даты.
    НЕТ form_id, current_step, fields, approvals.
  - GET /forms/{id}/register возвращает current_step, fields, но НЕ form_id.
  - GET /tasks/{id} возвращает ВСЁ (form_id, fields, approvals, comments...).

  - GET /inbox returns ONLY: id, author, responsible, text, dates.
    NO form_id, current_step, fields, approvals.
  - GET /forms/{id}/register returns current_step, fields, but NOT form_id.
  - GET /tasks/{id} returns EVERYTHING (form_id, fields, approvals, comments...).

Вывод / Conclusion:
  Для фильтрации по формам/шагам — используйте start_polling(form_id=...).
  Inbox-поллинг подходит только для «все входящие» без фильтрации,
  либо с enrich=True (но это N запросов get_task на каждый полл).

  For filtering by forms/steps — use start_polling(form_id=...).
  Inbox polling is only good for "all inbox" without filtering,
  or with enrich=True (but that's N get_task requests per poll).

Что показано / What is shown:
  - Сравнение данных inbox vs register vs get_task
  - start_polling с несколькими формами
  - Фильтрация по форме + шагу + полю
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
    TaskContext,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Учётные данные / Credentials ─────────────────────────────────────────────
LOGIN = "bot@example.com"
SECURITY_KEY = "YOUR_SECURITY_KEY"
BASE_URL = "https://pyrus.mycompany.com"  # on-premise (или убрать для облака)

# ── Формы для мониторинга / Forms to monitor ─────────────────────────────────
FORM_A = 321  # Первая форма / First form
FORM_B = 322  # Вторая форма / Second form (замените на реальный ID)

# ── Бот / Bot ────────────────────────────────────────────────────────────────

bot = PyrusBot(
    login=LOGIN,
    security_key=SECURITY_KEY,
    base_url=BASE_URL,
    requests_per_minute=30,
)

router = Router(name="multi_form")
dp = Dispatcher()
dp.include_router(router)


# ── Обработчики / Handlers ───────────────────────────────────────────────────


@router.task_received(FormFilter(FORM_A), StepFilter(6))
async def on_form_a(ctx: TaskContext) -> None:
    """Задача формы A на шаге 6 / Form A task at step 6."""
    print(f"[Form A] Task #{ctx.id}  step={ctx.step}")
    # ctx.get("Имя поля") — чтение поля по имени из интерфейса Pyrus
    # ctx.get("Field name") — read field by its Pyrus UI name
    await ctx.answer("Принято ботом")


@router.task_received(FormFilter(FORM_B), StepFilter([2, 3]))
async def on_form_b(ctx: TaskContext) -> None:
    """Задача формы B на шагах 2 или 3 / Form B task at steps 2 or 3."""
    print(f"[Form B] Task #{ctx.id}  step={ctx.step}")


@router.task_received(
    FormFilter([FORM_A, FORM_B]),
    FieldValueFilter(field_name="Статус", value=None),
)
async def on_empty_status(ctx: TaskContext) -> None:
    """Любая из двух форм, где поле 'Статус' пустое.
    Either form where the 'Status' field is empty."""
    print(f"[Empty status] Task #{ctx.id}")
    ctx.set("Статус", "В обработке")
    await ctx.answer()


# ── Диагностика: что видит inbox / Diagnostic: what inbox returns ────────────


async def show_inbox_vs_register() -> None:
    """Вспомогательная функция для сравнения ответов API.
    Helper to compare API responses side by side."""
    from aiopyrus import UserClient

    async with UserClient(login=LOGIN, security_key=SECURITY_KEY, base_url=BASE_URL) as client:
        # Inbox — скудные данные / Inbox — sparse data
        inbox = await client.get_inbox()
        if inbox:
            t = inbox[0]
            print(f"INBOX:    id={t.id}  form_id={t.form_id}  step={t.current_step}")
            # form_id=None, current_step=None

        # Register — есть step и fields, но нет form_id
        # Register — has step and fields, but no form_id
        reg = await client.get_register(FORM_A)
        if reg:
            t = reg[0]
            print(f"REGISTER: id={t.id}  form_id={t.form_id}  step={t.current_step}")
            # form_id=None, current_step=6

        # get_task — всё / get_task — everything
        if reg:
            full = await client.get_task(reg[0].id)
            print(f"TASK:     id={full.id}  form_id={full.form_id}  step={full.current_step}")
            # form_id=321, current_step=6


# ── Запуск / Start ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Раскомментируйте для диагностики / Uncomment for diagnostics:
    # asyncio.run(show_inbox_vs_register())

    # Polling нескольких форм — рекомендуемый способ
    # Polling multiple forms — recommended approach
    asyncio.run(
        dp.start_polling(
            bot,
            form_id=[FORM_A, FORM_B],
            interval=30,
            skip_old=True,
        )
    )

    # НЕ рекомендуется для фильтрации по форме:
    # NOT recommended for form-based filtering:
    #
    # asyncio.run(
    #     dp.start_inbox_polling(
    #         bot,
    #         enrich=True,   # +1 запрос get_task() на КАЖДУЮ задачу!
    #                        # +1 get_task() request per EVERY task!
    #         interval=60,
    #     )
    # )
