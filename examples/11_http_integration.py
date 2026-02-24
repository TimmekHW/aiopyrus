"""11_http_integration.py — HTTP-сервер для интеграции с внешними системами.
                           HTTP server for integration with external systems.

Сценарий / Scenario:
  Ваш Python-сервис поднимает HTTP API (aiohttp / FastAPI / ...).
  Внешняя система (PHP, 1С, фронтенд, другой микросервис) шлёт POST-запрос
  с task_id (или ссылкой). Сервис через UserClient делает всё в Pyrus:

    1. Получает задачу, вытаскивает «Описание» и «ФИО»
    2. Статус «Открыта» → «В работе», исполнитель «Тестов Тест Тестович»
    3. Передаёт данные во внутреннюю обработку (условная функция)
    4. Статус → «Выполнено», списывает 5 минут, апрувит

  Your Python service exposes an HTTP API.
  An external system (PHP, 1C, frontend, another microservice) sends a POST
  with task_id (or a link). The service uses UserClient to do everything in Pyrus.

Запуск / Run:
  pip install aiohttp aiopyrus
  python examples/11_http_integration.py

  Из PHP / From PHP:
    curl -X POST http://localhost:8080/process \
         -H "Content-Type: application/json" \
         -d '{"task_id": 12345678}'

  Или со ссылкой / Or with a link:
    curl -X POST http://localhost:8080/process \
         -H "Content-Type: application/json" \
         -d '{"link": "https://pyrus.com/t#id12345678"}'
"""

from __future__ import annotations

import logging
import re

from aiohttp import web

from aiopyrus import UserClient

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ── Настройки / Settings ─────────────────────────────────────────────────────

LOGIN = "user@example.com"
SECURITY_KEY = "YOUR_SECURITY_KEY"
# BASE_URL = "https://pyrus.mycompany.com"  # on-premise (если нужно)

HOST = "0.0.0.0"
PORT = 8080


# ── Бизнес-логика / Business logic ───────────────────────────────────────────


async def process_internally(description: str, fio: str) -> dict:
    """Условная внутренняя обработка — замените на свою логику.
    Mock internal processing — replace with your logic.

    Примеры реальных вызовов / Real-world examples:
      - httpx.post("http://erp.local/api/create_ticket", json={...})
      - rabbitmq_channel.publish(routing_key="tickets", body=json.dumps({...}))
      - db.execute("INSERT INTO tickets ...")
    """
    log.info("Processing: fio=%s, desc=%s", fio, description[:80])
    return {"status": "ok", "ticket": "INC-42"}


async def process_task(client: UserClient, task_id: int) -> dict:
    """Полный цикл обработки задачи в Pyrus.
    Full task processing cycle in Pyrus.
    """
    # 1. Получаем задачу / Fetch task
    ctx = await client.task_context(task_id)
    description = ctx.get("Описание", "нет описания")
    fio = ctx.get("ФИО", "не указано")
    log.info("Task #%d | ФИО: %s", ctx.id, fio)

    # 2. Статус → «В работе», исполнитель
    ctx.set("Статус", "В работе")
    ctx.set("Исполнитель", "Тестов Тест Тестович")
    await ctx.answer("Принято в работу (автоматически)")

    # 3. Внутренняя обработка / Internal processing
    result = await process_internally(str(description), str(fio))

    # 4. Статус → «Выполнено»
    ctx.set("Статус", "Выполнено")
    await ctx.answer(f"Обработано. Тикет: {result.get('ticket', 'N/A')}")

    # 5. Списываем 5 минут / Log 5 minutes
    await ctx.log_time(5, "Автообработка")

    # 6. Апрув / Approve
    await ctx.approve("Согласовано автоматически")

    return {"task_id": ctx.id, "result": result}


# ── HTTP-обработчики / HTTP handlers ─────────────────────────────────────────


def parse_task_id(data: dict) -> int | None:
    """Извлекает task_id из запроса — из поля task_id или из ссылки.
    Extracts task_id from request — from task_id field or from a link.
    """
    if "task_id" in data:
        return int(data["task_id"])
    if "link" in data:
        # https://pyrus.com/t#id12345678  или  https://pyrus.corp.ru/t#id12345678
        m = re.search(r"#id(\d+)", data["link"])
        if m:
            return int(m.group(1))
    return None


async def handle_process(request: web.Request) -> web.Response:
    """POST /process — обработать задачу по task_id или ссылке.
    POST /process — process a task by task_id or link.

    Body (JSON):
      {"task_id": 12345678}
      или / or
      {"link": "https://pyrus.com/t#id12345678"}
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    task_id = parse_task_id(data)
    if not task_id:
        return web.json_response(
            {"error": "task_id or link required"},
            status=400,
        )

    client: UserClient = request.app["pyrus_client"]

    try:
        result = await process_task(client, task_id)
        return web.json_response({"ok": True, **result})
    except Exception as exc:
        log.exception("Error processing task %d", task_id)
        return web.json_response({"error": str(exc)}, status=500)


async def handle_create(request: web.Request) -> web.Response:
    """POST /create — создать задачу в Pyrus из внешней системы.
    POST /create — create a task in Pyrus from an external system.

    Body (JSON):
      {"form_id": 228, "description": "Текст заявки", "fio": "Тестов Тест Тестович"}
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    form_id = data.get("form_id")
    if not form_id:
        return web.json_response({"error": "form_id required"}, status=400)

    client: UserClient = request.app["pyrus_client"]

    try:
        task = await client.create_task(
            form_id=int(form_id),
            text=data.get("description", ""),
            responsible=data.get("responsible"),
            fill_defaults=True,
        )
        log.info("Created task #%d on form %d", task.id, form_id)
        return web.json_response({"ok": True, "task_id": task.id})
    except Exception as exc:
        log.exception("Error creating task")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_health(request: web.Request) -> web.Response:
    """GET /health — проверка что сервис жив / health check."""
    return web.json_response({"status": "ok"})


# ── Жизненный цикл / Lifecycle ───────────────────────────────────────────────


async def on_startup(app: web.Application) -> None:
    """Создаём UserClient при старте сервера / Create UserClient on startup."""
    client = UserClient(login=LOGIN, security_key=SECURITY_KEY)
    await client.__aenter__()
    app["pyrus_client"] = client
    log.info("Pyrus client connected")


async def on_shutdown(app: web.Application) -> None:
    """Закрываем соединение / Close connection."""
    client: UserClient = app["pyrus_client"]
    await client.__aexit__(None, None, None)
    log.info("Pyrus client disconnected")


# ── Запуск / Run ─────────────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/health", handle_health)
    app.router.add_post("/process", handle_process)
    app.router.add_post("/create", handle_create)
    return app


if __name__ == "__main__":
    # python examples/11_http_integration.py
    #
    # Из PHP / From PHP:
    #   $response = file_get_contents('http://localhost:8080/process', false,
    #       stream_context_create(['http' => [
    #           'method' => 'POST',
    #           'header' => 'Content-Type: application/json',
    #           'content' => json_encode(['task_id' => 12345678]),
    #       ]]));
    #
    # Из curl:
    #   curl -X POST http://localhost:8080/process \
    #        -H "Content-Type: application/json" \
    #        -d '{"task_id": 12345678}'
    #
    #   curl -X POST http://localhost:8080/create \
    #        -H "Content-Type: application/json" \
    #        -d '{"form_id": 228, "description": "Новая заявка от PHP"}'
    #
    web.run_app(create_app(), host=HOST, port=PORT)
