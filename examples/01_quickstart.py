"""01_quickstart.py — Быстрый старт / Quick start.

Самый простой способ начать работу с aiopyrus.
The simplest way to start working with aiopyrus.

Что показано / What is shown:
  - Подключение через контекстный менеджер / Connection via context manager
  - Профиль текущего пользователя / Current user profile
  - Входящие задачи / Inbox tasks
  - Чтение полей через TaskContext (по имени из интерфейса Pyrus)
    / Reading fields via TaskContext (by name as shown in Pyrus UI)
  - Оставить комментарий через ctx.answer()
    / Leave a comment via ctx.answer()
"""

import asyncio

from aiopyrus import UserClient

# ── Учётные данные / Credentials ─────────────────────────────────────────────
# Берутся из: Настройки → Профиль → Ключ безопасности
# Found at:   Settings → Profile → Security key
LOGIN = "user@example.com"
SECURITY_KEY = "YOUR_SECURITY_KEY"
TASK_ID = 12345678


async def main() -> None:
    # Контекстный менеджер — соединение закрывается автоматически
    # Context manager — connection is closed automatically
    async with UserClient(login=LOGIN, security_key=SECURITY_KEY) as client:
        # ── Кто я? / Who am I? ──────────────────────────────────────────
        profile = await client.get_profile()
        print(f"Привет, {profile.first_name}!")  # Hello, ...!

        # ── Входящие / Inbox ─────────────────────────────────────────────
        inbox = await client.get_inbox()
        print(f"Задач во входящих: {len(inbox)}")  # Tasks in inbox: N

        # ── Задача по ID — через TaskContext (рекомендуемый способ) ───────
        # Task by ID — via TaskContext (recommended approach)
        ctx = await client.task_context(TASK_ID)

        # Читать поля по имени из интерфейса — без знания ID
        # Read fields by their UI name — no ID knowledge needed
        status = ctx.get("Статус задачи", "не задан")
        description = ctx.get("Описание", "")
        print(f"Статус: {status}")
        print(f"Описание: {description}")

        # ctx.id, ctx.step, ctx.closed — базовые свойства
        # ctx.id, ctx.step, ctx.closed — basic properties
        print(f"Задача #{ctx.id}  шаг={ctx.step}  закрыта={ctx.closed}")

        # ── Оставить комментарий / Leave a comment ───────────────────────
        # ctx.answer() отправляет комментарий + сбрасывает все set()
        # ctx.answer() sends comment and flushes all pending set()s
        # await ctx.answer("Принято в работу")   # раскомментировать! / uncomment!


if __name__ == "__main__":
    asyncio.run(main())
