"""13_debug_logging.py — Дебаг: посмотреть что библиотека отправляет в Pyrus.
                       Debug: see what the library sends to Pyrus.

Никаких специальных API в aiopyrus — всё через стандартный ``logging``.

No special APIs in aiopyrus — everything goes through the standard ``logging``.

Что показано / What is shown:
  - Включение всех логов одной строкой
  - Точечное включение по компонентам (session/dispatcher/...)
  - Подключение httpx-логов для низкоуровневых деталей (заголовки, connect)
  - Перенаправление логов в файл / в JSON для систем агрегации
"""

import asyncio
import logging
import sys

from aiopyrus import UserClient

LOGIN = "user@example.com"
SECURITY_KEY = "YOUR_SECURITY_KEY"
TASK_ID = 12345678


# ── 1. Самый простой способ — все aiopyrus-логи в stderr ────────────────────


def enable_simple_debug() -> None:
    """Простейший вариант — всё, что библиотека пишет, идёт в stderr."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        stream=sys.stderr,
    )


# ── 2. Точечно — только aiopyrus, без httpx/asyncio/прочего шума ───────────


def enable_aiopyrus_only_debug() -> None:
    """Шумят asyncio, httpx, urllib3 — а нам нужен только aiopyrus."""
    logging.basicConfig(level=logging.INFO)  # baseline INFO для всех
    logging.getLogger("aiopyrus").setLevel(logging.DEBUG)  # только мы — DEBUG


# ── 3. По компонентам — точечно выбрать что нужно ───────────────────────────


def enable_per_component_debug() -> None:
    """Loggers по областям:

    - aiopyrus.session    — HTTP-запросы, auth, retry
    - aiopyrus.client     — батч-операции (warnings про failed tasks)
    - aiopyrus.dispatcher — polling cycle, ошибки хендлеров
    - aiopyrus.filters    — нерезолвленные имена форм в FormFilter
    - aiopyrus.context    — pre-check обязательных полей
    - aiopyrus.webhook    — приём вебхуков
    - aiopyrus.rate_limiter — конфиг limiter
    """
    logging.basicConfig(level=logging.INFO)
    # Я хочу видеть только HTTP-запросы и polling-цикл, остальное молчит
    logging.getLogger("aiopyrus.session").setLevel(logging.DEBUG)
    logging.getLogger("aiopyrus.dispatcher").setLevel(logging.DEBUG)


# ── 4. Заодно httpx — для низкоуровневых деталей (заголовки, connect/close) ─


def enable_with_httpx() -> None:
    """httpx пишет запросы на уровень ниже — видны заголовки, connection pool."""
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("aiopyrus").setLevel(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.DEBUG)  # connect, send, recv


# ── 5. Логи в файл вместо stderr ────────────────────────────────────────────


def log_to_file(path: str = "aiopyrus.log") -> None:
    """Пишем DEBUG-логи aiopyrus в файл, в консоль — только INFO."""
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s")

    file_h = logging.FileHandler(path, encoding="utf-8")
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(fmt)

    console_h = logging.StreamHandler(sys.stderr)
    console_h.setLevel(logging.INFO)
    console_h.setFormatter(fmt)

    root = logging.getLogger("aiopyrus")
    root.setLevel(logging.DEBUG)
    root.addHandler(file_h)
    root.addHandler(console_h)
    root.propagate = False  # чтобы не дублировалось через root logger


# ── 6. Демо — что вы увидите при включённом DEBUG ──────────────────────────


async def demo() -> None:
    async with UserClient(login=LOGIN, security_key=SECURITY_KEY) as client:
        # Каждый из этих вызовов даст 2-3 строки в логе:
        #   → POST https://accounts.pyrus.com/api/v4/auth  body=['login', 'security_key']
        #      status=200  keys=['access_token', 'api_url', 'files_url']  rl_remaining=None
        #
        #   → GET https://api.pyrus.com/v4/profile  body=None
        #      status=200  keys=['person_id', 'first_name', ...]  rl_remaining=4999
        #   ← GET profile  84ms
        #
        #   → GET https://api.pyrus.com/v4/tasks/12345678  body=None
        #      status=200  keys=['task']  rl_remaining=4998
        #   ← GET tasks/12345678  213ms
        await client.get_profile()
        ctx = await client.task_context(TASK_ID)

        # Пишущие операции тоже видны:
        #   → POST https://api.pyrus.com/v4/tasks/12345678/comments  body=['text']
        #      status=200  keys=['task']  rl_remaining=4997
        await ctx.answer("Тест дебаг-лога")


if __name__ == "__main__":
    # Выберите способ — раскомментируйте один из:
    enable_simple_debug()
    # enable_aiopyrus_only_debug()
    # enable_per_component_debug()
    # enable_with_httpx()
    # log_to_file("aiopyrus.log")

    asyncio.run(demo())
