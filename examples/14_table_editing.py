"""14_table_editing.py — Редактирование полей-таблиц как DataFrame.
                       Editing table fields like a DataFrame.

``await ctx.table("Имя")`` открывает поле-таблицу как объект, с которым
работаешь по именам колонок — без знания row_id, col_id и форматов ячеек.
Значения резолвятся автоматически (имя → person_id, True/False → галочка,
строка каталога → item_id). Изменения ленивые — уходят одним запросом
при ``ctx.answer()``.

Open a table field with ``await ctx.table("Name")`` and work with it by
column names — no row_id / col_id / cell formats. Values auto-resolve;
edits are lazy and flushed on ``ctx.answer()``.

Что показано / What is shown:
  - Чтение таблицы, ASCII-рендер
  - Фильтрация where()/find() как в SQLAlchemy
  - Правка ячеек, добавление и удаление строк как в Excel
  - Отправка всех изменений одним запросом
"""

import asyncio

from aiopyrus import UserClient

LOGIN = "user@example.com"
SECURITY_KEY = "YOUR_SECURITY_KEY"
TASK_ID = 12345678
TABLE_FIELD = "План работ"  # имя поля-таблицы в вашей форме


async def main() -> None:
    async with UserClient(login=LOGIN, security_key=SECURITY_KEY) as client:
        ctx = await client.task_context(TASK_ID)

        # ── Открыть таблицу ──────────────────────────────────────────
        tbl = await ctx.table(TABLE_FIELD)

        # ── Чтение — как pandas / список ─────────────────────────────
        print(f"Колонки: {tbl.columns}")
        print(f"Строк: {len(tbl)}")
        print(tbl)  # красивый ASCII-рендер всей таблицы

        # Доступ по индексу и имени колонки
        first = tbl[0]
        print(f"Первая строка: {first['Что планируется сделать']}")
        print(f"  Ответственный: {first['Ответственный']}")
        print(f"  Выполнено: {first['Выполнено']}")

        # Итерация
        for row in tbl:
            mark = "✓" if row["Выполнено"] else " "
            print(f"  [{mark}] {row['Что планируется сделать']}")

        # ── Фильтрация — как SQLAlchemy ──────────────────────────────
        # Строки где галочка не стоит
        todo = tbl.where(**{"Выполнено": False})
        print(f"\nНевыполненных: {len(todo)}")

        # По подстроке (регистронезависимо) — для text / person
        mine = tbl.where(**{"Ответственный": "Колбасенко"})
        print(f"Мои строки: {len(mine)}")

        # Первая под условие
        row = tbl.find(**{"Что планируется сделать": "Ревью задачи"})

        # ── Правка — как Excel ───────────────────────────────────────
        # Отметить галочку
        if row is not None:
            row["Выполнено"] = True

        # Переназначить ответственного во всех невыполненных
        # (имя резолвится в person_id автоматически)
        for r in tbl.where(**{"Выполнено": False}):
            r["Ответственный"] = "Данил Колбасенко"

        # Несколько ячеек сразу
        if row is not None:
            row.update({"Выполнено": True, "Ответственный": "Данил Колбасенко"})

        # ── Добавить строку ──────────────────────────────────────────
        tbl.add(
            **{
                "Что планируется сделать": "03/26 Новая задача",
                "Ответственный": "Данил Колбасенко",  # → person_id авто
                "Выполнено": False,  # → "unchecked"
            }
        )

        # ── Удалить строку ───────────────────────────────────────────
        old = tbl.find(**{"Что планируется сделать": "устаревшая запись"})
        if old is not None:
            old.delete()

        # Сколько изменений накопилось
        print(f"\nНакоплено изменений: {ctx.pending_count()}")

        # ── Отправка — всё одним запросом (+ можно fill() обычных полей) ──
        ctx.fill("Статус", "В работе")  # обычное поле — уедет вместе с таблицей
        await ctx.answer("Обновил план выполнения")

        # Экспорт как список словарей (как DataFrame.to_dict('records'))
        # records = tbl.to_records()


if __name__ == "__main__":
    asyncio.run(main())
