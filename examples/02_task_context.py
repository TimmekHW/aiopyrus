"""02_task_context.py — TaskContext: человекочитаемый доступ к задачам.
                       TaskContext: human-readable task access.

TaskContext — главная фича библиотеки. Читайте и пишите поля по имени,
как они называются в интерфейсе Pyrus. Без знания ID, choice_id, person_id.

TaskContext is the library's killer feature. Read and write fields by name
as they appear in Pyrus. No IDs, choice_ids, or person_ids needed.

Что показано / What is shown:
  - ctx["Поле"]            — чтение (KeyError если нет поля)
  - ctx.get("Поле", def)   — чтение с дефолтом
  - ctx.raw("Поле")        — сырой FormField объект
  - ctx.find("%паттерн%")  — поиск по wildcard
  - ctx.set().set()        — ленивая запись, чейнинг
  - ctx.discard()          — отмена накопленных set()
  - ctx.answer()           — комментарий + сброс полей
  - ctx.approve/reject/finish() — шаги согласования
  - ctx.reassign()         — переназначить (по имени)
  - ctx.log_time()         — трекинг времени
  - ctx.reply()            — ответить на комментарий
"""

import asyncio

from aiopyrus import UserClient

LOGIN = "user@example.com"
SECURITY_KEY = "YOUR_SECURITY_KEY"

# ID задач для демонстрации. Подставьте реальные.
# Task IDs for demonstration. Replace with real ones.
HELPDESK_TASK_ID = 12345678  # IT-заявка / IT request form task
PAYMENT_TASK_ID = 12345679  # Платёж / Payment approval form task


# ── 1. Чтение полей / Reading fields ────────────────────────────────────────


async def demo_reading(client: UserClient) -> None:
    """Все способы чтения полей / All field reading methods."""
    print("\n== Чтение полей / Reading fields ==")

    ctx = await client.task_context(HELPDESK_TASK_ID)

    # ctx["Поле"] — KeyError если поле не найдено
    # ctx["Field"] — raises KeyError if field not found
    try:
        problem_type = ctx["Тип проблемы"]  # multiple_choice -> str
        executor = ctx["Исполнитель"]  # person field -> "Имя Фамилия"
        print(f"Тип проблемы: {problem_type}")
        print(f"Исполнитель: {executor}")
    except KeyError as e:
        print(f"Поле не найдено: {e}")

    # ctx.get() — безопасное чтение с дефолтом
    # ctx.get() — safe read with a default
    priority = ctx.get("Приоритет", "Средний")
    case_num = ctx.get("Номер кейса", "не создан")
    print(f"Приоритет: {priority}  Кейс: {case_num}")

    # ctx.raw() — получить FormField объект для низкоуровневого доступа
    # ctx.raw() — get the raw FormField object for low-level access
    raw_field = ctx.raw("Тип проблемы")
    if raw_field:
        print(f"raw: id={raw_field.id}  type={raw_field.type}  value={raw_field.value!r}")

    # ctx.find("%wildcard%") — поиск по маске (% = любые символы, как SQL LIKE)
    # ctx.find("%wildcard%") — wildcard search (% = any chars, SQL LIKE style)
    desc = ctx.find("%описан%", "нет описания")  # содержит "описан" / contains
    cat = ctx.find("Категория%")  # начинается с / starts with
    print(f"Описание (wildcard): {desc}")
    print(f"Категория (wildcard): {cat}")

    # Свойства / Properties
    print(f"\nid={ctx.id}  step={ctx.step}  closed={ctx.closed}  form_id={ctx.form_id}")


# ── 2. Запись полей / Writing fields ─────────────────────────────────────────


async def demo_writing(client: UserClient) -> None:
    """Ленивая запись и отправка / Lazy write and send."""
    print("\n== Запись полей / Writing fields ==")

    ctx = await client.task_context(HELPDESK_TASK_ID)

    # ctx.set() — ленивая запись. Ничего не отправляется до answer()/approve()/...
    # ctx.set() — lazy write. Nothing is sent until answer()/approve()/...
    # Строки автоматически резолвятся: имя варианта -> choice_id, имя -> person_id
    # Strings auto-resolve: choice name -> choice_id, person name -> person_id
    ctx.set("Статус задачи", "В работе")  # multiple_choice: имя -> choice_id
    ctx.set("Исполнитель", "Данил Колбасенко")  # person: имя -> person_id
    ctx.set("Номер кейса", "INC-001")  # text: как есть / as-is

    # ctx.set() возвращает self — можно чейнить
    # ctx.set() returns self — chainable
    ctx.set("Приоритет", "Высокий").set("SLA", "4h")

    print(f"Накопленных изменений: {ctx.pending_count()}")  # 5

    # ctx.discard() — отменить все set() без отправки
    # ctx.discard() — cancel all set()s without sending
    ctx.discard()
    print(f"После discard(): {ctx.pending_count()}")  # 0

    # Ставим снова / Set again
    ctx.set("Статус задачи", "В работе").set("Исполнитель", "Данил Колбасенко")

    # ctx.answer() — отправить комментарий + сбросить все set() одним запросом
    # ctx.answer() — send comment + flush all set()s in one API request
    # await ctx.answer("Задача принята в работу")   # раскомментировать! / uncomment!
    print("  (отправка закомментирована / send is commented out)")


# ── 3. Согласование / Approval flow ─────────────────────────────────────────


async def demo_approval(client: UserClient) -> None:
    """Согласование, завершение, переназначение / Approval, finish, reassign."""
    print("\n== Согласование / Approval flow ==")

    ctx = await client.task_context(PAYMENT_TASK_ID)

    amount_str = ctx.get("Сумма", "0")
    try:
        amount = float(str(amount_str).replace(",", ".").replace(" ", ""))
    except (ValueError, AttributeError):
        amount = 0.0

    print(f"Сумма платежа: {amount_str}")

    if amount > 500_000:
        # Отклонить / Reject
        ctx.set("Причина отклонения", "Превышение лимита")
        # await ctx.reject("Сумма превышает лимит. Передаю на ручное рассмотрение.")
        print("  -> reject (закомментировано / commented out)")
    else:
        # Одобрить / Approve
        ctx.set("Статус", "Одобрено")
        # await ctx.approve("Одобрено автоматически.")
        print("  -> approve (закомментировано / commented out)")

    # ctx.finish() — завершить задачу (не approve, а именно закрыть)
    # ctx.finish() — finish the task (close it, not approve)
    # await ctx.finish("Выполнено")

    # ctx.reassign() — переназначить (person_id разрешается автоматически по имени)
    # ctx.reassign() — reassign (person_id resolved automatically by name)
    # await ctx.reassign("Данил Колбасенко", "Передаю для финального согласования")


# ── 4. Трекинг и ответы / Time tracking and replies ─────────────────────────


async def demo_time_and_replies(client: UserClient) -> None:
    """Трекинг времени и ответы на комментарии / Time tracking and replies."""
    print("\n== Трекинг и ответы / Time tracking and replies ==")

    ctx = await client.task_context(HELPDESK_TASK_ID)

    # ctx.log_time() — списать время на задачу
    # ctx.log_time() — log time spent on task
    await ctx.log_time(90, "Анализ и диагностика проблемы")  # 90 минут / minutes
    print("  log_time(90, ...) (закомментировано / commented out)")

    # ctx.reply() — ответить на конкретный комментарий (треды)
    # ctx.reply() — reply to a specific comment (threaded)
    if ctx.task.comments:
        first = ctx.task.comments[0]
        print(f"  Первый комментарий: id={first.id}")
        await ctx.reply(first.id, "Уточняю детали...")

    # Приватный комментарий / Private comment (виден только участникам / visible to participants only)
    await ctx.answer("Только для внутреннего пользования", private=True)


# ── Запуск / Run ─────────────────────────────────────────────────────────────


async def main() -> None:
    async with UserClient(login=LOGIN, security_key=SECURITY_KEY) as client:
        await demo_reading(client)
        await demo_writing(client)
        await demo_approval(client)
        await demo_time_and_replies(client)


if __name__ == "__main__":
    asyncio.run(main())
