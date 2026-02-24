"""09_auto_processing.py — Автоматическая обработка заявки по ссылке.
                          Automatic task processing by link.

Сценарий / Scenario:
  1. Получаем ссылку на задачу (task_id из URL)
  2. Вытаскиваем «Описание» и «ФИО»
  3. Меняем статус «Открыта» → «В работе»
  4. Ставим исполнителя «Тестов Тест Тестович»
  5. Передаём описание + ФИО во внешний микросервис (условная функция)
  6. Получаем ответ
  7. Меняем статус «В работе» → «Выполнено»
  8. Списываем 5 минут
  9. Делаем апрув

Всё через UserClient — без бота, без polling, без webhook.
All via UserClient — no bot, no polling, no webhook.
"""

import asyncio

from aiopyrus import UserClient

LOGIN = "user@example.com"
SECURITY_KEY = "YOUR_SECURITY_KEY"

# Из ссылки https://pyrus.com/t#id12345678 берём task_id
# From link https://pyrus.com/t#id12345678 we extract task_id
TASK_ID = 12345678


# ── Условный микросервис / Mock microservice ─────────────────────────────────


async def call_external_service(description: str, fio: str) -> dict:
    """Имитация вызова внешнего микросервиса.
    Simulates an external microservice call.

    В реальности — httpx.post() к вашему API, RabbitMQ publish, gRPC и т.д.
    In practice — httpx.post() to your API, RabbitMQ publish, gRPC, etc.
    """
    print("  -> Отправляем в микросервис:")
    print(f"     Описание: {description[:80]}...")
    print(f"     ФИО: {fio}")

    # Имитация ответа / Simulated response
    await asyncio.sleep(0.5)
    return {"status": "ok", "ticket": "INC-42"}


# ── Основная логика / Main logic ─────────────────────────────────────────────


async def process_task(client: UserClient, task_id: int) -> None:
    """Полный цикл обработки задачи / Full task processing cycle."""

    # 1. Получаем задачу / Fetch the task
    ctx = await client.task_context(task_id)
    print(f"Задача #{ctx.id} | step={ctx.step} | closed={ctx.closed}")

    # 2. Вытаскиваем поля / Extract fields
    description = ctx.get("Описание", "нет описания")
    fio = ctx.get("ФИО", "не указано")
    print(f"Описание: {description}")
    print(f"ФИО: {fio}")

    # 3. Статус «Открыта» → «В работе», ставим исполнителя
    #    Status "Открыта" → "В работе", set executor
    ctx.set("Статус", "В работе")
    ctx.set("Исполнитель", "Тестов Тест Тестович")
    await ctx.answer("Задача принята в работу")
    print("Статус -> В работе, исполнитель назначен")

    # 4. Вызываем внешний сервис / Call external service
    result = await call_external_service(str(description), str(fio))
    print(f"Ответ микросервиса: {result}")

    # 5. Статус «В работе» → «Выполнено»
    #    Status "В работе" → "Выполнено"
    ctx.set("Статус", "Выполнено")
    await ctx.answer(f"Обработано. Тикет: {result.get('ticket', 'N/A')}")
    print("Статус -> Выполнено")

    # 6. Списываем 5 минут / Log 5 minutes
    await ctx.log_time(5, "Автоматическая обработка заявки")
    print("Списано 5 минут")

    # 7. Апрув / Approve
    await ctx.approve("Согласовано автоматически")
    print("Задача согласована")


# ── Запуск / Run ─────────────────────────────────────────────────────────────


async def main() -> None:
    # Парсим task_id из ссылки / Parse task_id from URL
    # Пример: "https://pyrus.com/t#id12345678" → 12345678
    link = "https://pyrus.com/t#id12345678"
    task_id = int(link.split("#id")[-1])

    async with UserClient(login=LOGIN, security_key=SECURITY_KEY) as client:
        await process_task(client, task_id)


if __name__ == "__main__":
    asyncio.run(main())
