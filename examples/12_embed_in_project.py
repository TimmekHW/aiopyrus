"""12_embed_in_project.py — Встраивание aiopyrus в существующий Python-проект.
                           Embedding aiopyrus into an existing Python project.

aiopyrus — это просто библиотека. Импортируйте UserClient в свой проект
и вызывайте методы Pyrus API откуда угодно: из FastAPI эндпоинта,
Django view, Celery таски, CLI-скрипта, телеграм-бота.

aiopyrus is just a library. Import UserClient into your project
and call Pyrus API methods from anywhere: FastAPI endpoint,
Django view, Celery task, CLI script, Telegram bot.

Ниже — 4 примера интеграции / Below — 4 integration examples:
  1. FastAPI — эндпоинт принимает task_id, обрабатывает в Pyrus
  2. Django — view обрабатывает POST от фронтенда
  3. Celery — фоновая задача
  4. Простой скрипт — обработка списка задач из CSV/БД
"""

from __future__ import annotations

from aiopyrus import UserClient

# =============================================================================
# Общий модуль — pyrus_service.py в вашем проекте
# Shared module — pyrus_service.py in your project
# =============================================================================

# Вынесите логику работы с Pyrus в отдельный модуль,
# чтобы не дублировать код во view/endpoint/task.
#
# Extract Pyrus logic into a separate module
# to avoid duplicating code across views/endpoints/tasks.


async def get_pyrus_client() -> UserClient:
    """Фабрика клиента. В реальном проекте — singleton или DI.
    Client factory. In a real project — singleton or DI.
    """
    return UserClient(
        login="user@example.com",
        security_key="YOUR_SECURITY_KEY",
        # base_url="https://pyrus.mycompany.com",  # on-premise
    )


async def process_task_in_pyrus(task_id: int) -> dict:
    """Полный цикл обработки задачи — вызывайте откуда угодно.
    Full task processing cycle — call from anywhere.
    """
    async with await get_pyrus_client() as client:
        ctx = await client.task_context(task_id)

        # Вытаскиваем поля / Extract fields
        description = ctx.get("Описание", "нет описания")
        fio = ctx.get("ФИО", "не указано")

        # Статус → «В работе», исполнитель
        ctx.set("Статус", "В работе")
        ctx.set("Исполнитель", "Тестов Тест Тестович")
        await ctx.answer("Принято в работу")

        # ... ваша бизнес-логика / your business logic ...

        # Статус → «Выполнено»
        ctx.set("Статус", "Выполнено")
        await ctx.answer("Обработано")

        # Списываем 5 минут / Log 5 minutes
        await ctx.log_time(5, "Автообработка")

        # Апрув / Approve
        await ctx.approve("Согласовано автоматически")

        return {"task_id": ctx.id, "fio": str(fio), "description": str(description)}


async def create_task_in_pyrus(form_id: int, text: str, responsible: int | None = None) -> int:
    """Создать задачу в Pyrus — вызывайте из любого фреймворка.
    Create a task in Pyrus — call from any framework.
    """
    async with await get_pyrus_client() as client:
        task = await client.create_task(
            form_id=form_id,
            text=text,
            responsible=responsible,
            fill_defaults=True,
        )
        return task.id


# =============================================================================
# 1. FastAPI
# =============================================================================
#
# # app/routes/pyrus.py
#
# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel
# from your_project.pyrus_service import process_task_in_pyrus, create_task_in_pyrus
#
# app = FastAPI()
#
#
# class ProcessRequest(BaseModel):
#     task_id: int
#
#
# class CreateRequest(BaseModel):
#     form_id: int
#     text: str
#     responsible: int | None = None  # person_id
#
#
# @app.post("/pyrus/process")
# async def process_task(req: ProcessRequest):
#     """PHP/фронт шлёт task_id — мы обрабатываем в Pyrus."""
#     try:
#         result = await process_task_in_pyrus(req.task_id)
#         return {"ok": True, **result}
#     except Exception as exc:
#         raise HTTPException(status_code=500, detail=str(exc))
#
#
# @app.post("/pyrus/create")
# async def create_task(req: CreateRequest):
#     """Создать задачу в Pyrus из внешней системы."""
#     task_id = await create_task_in_pyrus(req.form_id, req.text, req.responsible)
#     return {"ok": True, "task_id": task_id}


# =============================================================================
# 2. Django (async view)
# =============================================================================
#
# # app/views.py
#
# import json
# from django.http import JsonResponse
# from your_project.pyrus_service import process_task_in_pyrus
#
#
# async def pyrus_process(request):
#     """POST /pyrus/process — принимает task_id от PHP/фронта."""
#     if request.method != "POST":
#         return JsonResponse({"error": "POST only"}, status=405)
#
#     data = json.loads(request.body)
#     task_id = data.get("task_id")
#     if not task_id:
#         return JsonResponse({"error": "task_id required"}, status=400)
#
#     try:
#         result = await process_task_in_pyrus(int(task_id))
#         return JsonResponse({"ok": True, **result})
#     except Exception as exc:
#         return JsonResponse({"error": str(exc)}, status=500)


# =============================================================================
# 3. Celery (фоновая задача / background task)
# =============================================================================
#
# # app/tasks.py
#
# import asyncio
# from celery import Celery
# from your_project.pyrus_service import process_task_in_pyrus
#
# celery_app = Celery("myapp", broker="redis://localhost:6379/0")
#
#
# @celery_app.task
# def process_pyrus_task(task_id: int):
#     """Celery worker обрабатывает задачу в фоне."""
#     result = asyncio.run(process_task_in_pyrus(task_id))
#     return result
#
#
# # Вызов из view / Call from view:
# #   process_pyrus_task.delay(12345678)


# =============================================================================
# 4. Простой скрипт — обработка списка задач
#    Simple script — batch processing
# =============================================================================


async def batch_process() -> None:
    """Обработать список task_id из БД, CSV, или просто список.
    Process a list of task_ids from DB, CSV, or just a list.
    """
    # Из БД, CSV, аргументов — откуда угодно
    # From DB, CSV, CLI args — anywhere
    task_ids = [12345678, 12345679, 12345680]

    async with await get_pyrus_client() as client:
        for task_id in task_ids:
            try:
                ctx = await client.task_context(task_id)
                fio = ctx.get("ФИО", "не указано")
                desc = ctx.get("Описание", "нет описания")
                print(f"Task #{task_id}: {fio} — {desc}")

                ctx.set("Статус", "В работе")
                ctx.set("Исполнитель", "Тестов Тест Тестович")
                await ctx.answer("Принято")

                # ... обработка ...

                ctx.set("Статус", "Выполнено")
                await ctx.answer("Выполнено")
                await ctx.log_time(5, "Автообработка")
                await ctx.approve("Согласовано")

                print("  -> OK")
            except Exception as exc:
                print(f"  -> Error: {exc}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(batch_process())
