"""TableProxy — работа с полями-таблицами Pyrus как с DataFrame.

Работайте с табличным полем через **имена колонок**, как в интерфейсе
Pyrus — без знания ``row_id``, ``col_id``, форматов ячеек и структуры
payload. Значения резолвятся автоматически: имя человека → ``person_id``,
``True/False`` → checkmark, строка каталога → ``item_id``.

Work with a Pyrus table field like a DataFrame — by column names,
with automatic value resolution and lazy write.

Быстрый старт / Quick start
---------------------------

.. code-block:: python

    ctx = await client.task_context(12345678)
    tbl = await ctx.table("План работ")

    # ── Чтение — как pandas / список ────────────────────────────────
    print(tbl.columns)          # ['Что сделать', 'Ответственный', 'Выполнено']
    print(len(tbl))             # 7
    for row in tbl:
        print(row["Что сделать"], "→", row["Ответственный"], row["Выполнено"])
    print(tbl)                  # красивый ASCII-рендер всей таблицы

    # ── Фильтрация — как SQLAlchemy ─────────────────────────────────
    todo = tbl.where(Выполнено=False)                # по имени колонки
    mine = tbl.where(**{"Ответственный": "Колбасенко"})  # имена с пробелами
    row  = tbl.find(**{"Что сделать": "Ревью задачи"})

    # ── Правка — как Excel ──────────────────────────────────────────
    row["Выполнено"] = True                          # отметить галочку
    for r in tbl.where(Выполнено=False):
        r["Ответственный"] = "Колбасенко"            # имя → person_id авто

    # ── Добавление / удаление строк ─────────────────────────────────
    tbl.add(**{
        "Что сделать": "03/26 Ревью задачи",
        "Ответственный": "Колбасенко",
        "Выполнено": False,
    })
    tbl.find(**{"Что сделать": "старая запись"}).delete()

    # ── Отправка — вместе с обычными полями, одним запросом ─────────
    await ctx.answer("Обновил план")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, overload

from aiopyrus.types.form import FieldType, FormField
from aiopyrus.utils.context import _read_field

if TYPE_CHECKING:
    from collections.abc import Iterator

    from aiopyrus.utils.context import TaskContext


# ---------------------------------------------------------------------------
# Column metadata
# ---------------------------------------------------------------------------


class Column:
    """Метаданные одной колонки таблицы: id + имя + тип."""

    __slots__ = ("id", "name", "type")

    def __init__(self, id: int, name: str, type: str | None) -> None:
        self.id = id
        self.name = name
        self.type = type

    def __repr__(self) -> str:
        return f"<Column id={self.id} name={self.name!r} type={self.type!r}>"


# ---------------------------------------------------------------------------
# Row
# ---------------------------------------------------------------------------


class Row:
    """Одна строка таблицы — доступ к ячейкам по именам колонок.

    Dict-подобный интерфейс: ``row["Колонка"]`` для чтения,
    ``row["Колонка"] = value`` для (ленивой) записи.
    """

    __slots__ = ("_table", "_row_id", "_cells", "_changes", "_position", "_is_new", "_deleted")

    def __init__(
        self,
        table: TableProxy,
        row_id: int | None,
        cells: dict[int, FormField],
        position: int | None = None,
        *,
        is_new: bool = False,
    ) -> None:
        self._table = table
        self._row_id = row_id  # None для ещё-не-отправленных новых строк
        self._cells = cells  # col_id → FormField (прочитанные значения)
        self._changes: dict[int, Any] = {}  # col_id → новое значение (ленивое)
        self._position = position
        self._is_new = is_new
        self._deleted = False

    # -- reading -------------------------------------------------------

    def __getitem__(self, column: str) -> Any:
        col = self._table._column(column)
        if col.id in self._changes:
            return self._changes[col.id]  # то, что присвоили — как есть
        cell = self._cells.get(col.id)
        if cell is not None:
            return _read_field(cell)
        # Pyrus не присылает ячейку у непроставленной галочки — трактуем как False
        if col.type in ("checkmark", "flag"):
            return False
        return None

    def get(self, column: str, default: Any = None) -> Any:
        try:
            col = self._table._column(column)
        except KeyError:
            return default
        if col.id in self._changes:
            val = self._changes[col.id]
            return val if val is not None else default
        cell = self._cells.get(col.id)
        if cell is not None:
            val = _read_field(cell)
            return val if val is not None else default
        if col.type in ("checkmark", "flag"):
            return False
        return default

    # -- writing (lazy) ------------------------------------------------

    def __setitem__(self, column: str, value: Any) -> None:
        col = self._table._column(column)
        self._changes[col.id] = value
        self._table._dirty = True

    def set(self, column: str, value: Any) -> Row:
        """Задать значение ячейки (чейнится)."""
        self[column] = value
        return self

    def update(self, values: dict[str, Any]) -> Row:
        """Задать несколько ячеек сразу из dict ``{колонка: значение}``."""
        for col_name, val in values.items():
            self[col_name] = val
        return self

    def delete(self) -> None:
        """Пометить строку на удаление (отправится при ``ctx.answer()``)."""
        self._deleted = True
        self._table._dirty = True

    # -- introspection -------------------------------------------------

    @property
    def row_id(self) -> int | None:
        """``row_id`` строки, или ``None`` если строка ещё не отправлена."""
        return self._row_id

    def to_dict(self) -> dict[str, Any]:
        """Строка как ``{имя_колонки: значение}`` (с учётом изменений)."""
        out: dict[str, Any] = {}
        for col in self._table._columns:
            out[col.name] = self[col.name]
        return out

    def __repr__(self) -> str:
        flag = " NEW" if self._is_new else ""
        flag += " DELETED" if self._deleted else ""
        return f"<Row row_id={self._row_id}{flag} {self.to_dict()}>"


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------


class TableProxy:
    """Таблица Pyrus как DataFrame — чтение, фильтрация, правка по именам колонок.

    Создаётся через ``await ctx.table("Имя таблицы")``. Все изменения
    ленивые — отправляются на сервер при следующем ``ctx.answer()`` /
    ``ctx.approve()`` / ``ctx.finish()``, вместе с обычными ``ctx.fill()``.
    """

    def __init__(
        self,
        ctx: TaskContext,
        field: FormField,
        columns: list[Column],
        rows: list[Row],
    ) -> None:
        self._ctx = ctx
        self._field = field
        self._columns = columns
        self._by_name: dict[str, Column] = {c.name.casefold(): c for c in columns}
        self._by_id: dict[int, Column] = {c.id: c for c in columns}
        self._rows = rows
        self._dirty = False

    # -- column lookup -------------------------------------------------

    def _column(self, name_or_id: str | int) -> Column:
        if isinstance(name_or_id, int):
            col = self._by_id.get(name_or_id)
        else:
            col = self._by_name.get(name_or_id.casefold())
        if col is None:
            available = ", ".join(repr(c.name) for c in self._columns)
            raise KeyError(
                f"Column {name_or_id!r} not found in table {self._field.name!r}. "
                f"Available columns: {available}"
            )
        return col

    @property
    def columns(self) -> list[str]:
        """Список имён колонок в порядке формы."""
        return [c.name for c in self._columns]

    @property
    def name(self) -> str:
        """Имя таблицы (как в форме)."""
        return self._field.name or f"table#{self._field.id}"

    @property
    def rows(self) -> list[Row]:
        """Все живые (не удалённые) строки."""
        return [r for r in self._rows if not r._deleted]

    # -- container protocol --------------------------------------------

    def __iter__(self) -> Iterator[Row]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    @overload
    def __getitem__(self, index: int) -> Row: ...
    @overload
    def __getitem__(self, index: slice) -> list[Row]: ...
    def __getitem__(self, index: int | slice) -> Row | list[Row]:
        return self.rows[index]

    def __bool__(self) -> bool:
        return bool(self.rows)

    # -- filtering (SQLAlchemy-style) ----------------------------------

    def where(self, **conditions: Any) -> list[Row]:
        """Вернуть строки, удовлетворяющие всем условиям ``колонка=значение``.

        Сравнение:

        - ``str`` — регистронезависимое **вхождение подстроки**
          (``Ответственный="Фатт"`` найдёт «Колбасенко»);
        - ``bool`` / ``None`` / число — **точное** равенство.

        Имена колонок с пробелами — через ``**{"Имя колонки": значение}``.

        Example::

            tbl.where(Выполнено=False)
            tbl.where(**{"Ответственный": "Колбасенко", "Выполнено": True})
        """
        result: list[Row] = []
        for row in self.rows:
            if all(_match(row.get(col), val) for col, val in conditions.items()):
                result.append(row)
        return result

    def find(self, **conditions: Any) -> Row | None:
        """Первая строка под условия ``where(...)``, или ``None``."""
        rows = self.where(**conditions)
        return rows[0] if rows else None

    def first(self) -> Row | None:
        """Первая живая строка, или ``None``."""
        rows = self.rows
        return rows[0] if rows else None

    # -- mutation ------------------------------------------------------

    def add(self, position: int | None = None, **values: Any) -> Row:
        """Добавить новую строку. Значения — по именам колонок.

        Значения резолвятся так же, как в ячейках: имя человека →
        ``person_id``, ``True/False`` → галочка, строка каталога → ``item_id``.

        Имена колонок с пробелами — через ``**{...}``.

        Example::

            tbl.add(**{
                "Что сделать": "Новая задача",
                "Ответственный": "Колбасенко",   # → person_id авто
                "Выполнено": False,
            })

        Returns созданную :class:`Row` (чейнится: ``.set()`` / ``.update()``).
        """
        row = Row(self, row_id=None, cells={}, position=position, is_new=True)
        for col_name, val in values.items():
            # проверяем что колонка существует + запоминаем изменение
            row[col_name] = val
        self._rows.append(row)
        self._dirty = True
        return row

    def remove(self, row: Row) -> None:
        """Пометить строку на удаление."""
        row.delete()

    def clear(self) -> None:
        """Пометить все строки на удаление."""
        for row in self._rows:
            row.delete()
        self._dirty = True

    # -- export --------------------------------------------------------

    def to_records(self) -> list[dict[str, Any]]:
        """Все живые строки как ``list[dict]`` (как ``DataFrame.to_dict('records')``)."""
        return [row.to_dict() for row in self.rows]

    # -- payload build (used by TaskContext._flush) --------------------

    async def _build_update(self) -> dict[str, Any] | None:
        """Собрать ``{"id": table_id, "value": [...]}`` или ``None`` если нет изменений."""
        if not self._dirty:
            return None
        value: list[dict[str, Any]] = []
        for row in self._rows:
            if row._deleted:
                if row._row_id is not None:  # удалять имеет смысл только существующие
                    value.append({"row_id": row._row_id, "delete": True})
                continue

            if row._is_new:
                cells = await self._resolve_cells(row._changes)
                entry: dict[str, Any] = {"cells": cells}
                if row._position is not None:
                    entry["position"] = row._position
                value.append(entry)
            elif row._changes:
                cells = await self._resolve_cells(row._changes)
                value.append({"row_id": row._row_id, "cells": cells})
            # неизменённые существующие строки не отправляем — Pyrus их не трогает

        if not value:
            return None
        return {"id": self._field.id, "value": value}

    async def _resolve_cells(self, changes: dict[int, Any]) -> list[dict[str, Any]]:
        cells: list[dict[str, Any]] = []
        for col_id, val in changes.items():
            col = self._by_id[col_id]
            ftype = None
            if col.type:
                try:
                    ftype = FieldType(col.type)
                except ValueError:
                    ftype = None
            # синтетический FormField колонки — переиспользуем весь резолв ctx
            col_field = FormField(id=col.id, type=ftype, name=col.name)
            cell = await self._ctx._resolve(col_field, val)
            cells.append(cell)
        return cells

    # -- pretty print (ASCII table) ------------------------------------

    def __repr__(self) -> str:
        return self._render()

    __str__ = __repr__

    def _render(self, max_col: int = 30) -> str:
        headers = self.columns
        if not headers:
            return f"<TableProxy {self.name!r} (нет колонок)>"

        def fmt(v: Any) -> str:
            if v is None:
                return ""
            if v is True:
                return "✓"
            if v is False:
                return "·"
            s = str(v).replace("\n", " ")
            return s if len(s) <= max_col else s[: max_col - 1] + "…"

        rows_disp = [[fmt(row.get(h)) for h in headers] for row in self.rows]
        widths = [
            max(len(h), *(len(r[i]) for r in rows_disp)) if rows_disp else len(h)
            for i, h in enumerate(headers)
        ]

        def line(cells: list[str]) -> str:
            return "│ " + " │ ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " │"

        bar = "┼".join("─" * (w + 2) for w in widths)
        top = "┬".join("─" * (w + 2) for w in widths)
        bot = "┴".join("─" * (w + 2) for w in widths)
        out = [f"Таблица «{self.name}» — {len(self.rows)} строк"]
        out.append("┌" + top + "┐")
        out.append(line(headers))
        out.append("├" + bar + "┤")
        for r in rows_disp:
            out.append(line(r))
        out.append("└" + bot + "┘")
        return "\n".join(out)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _match(actual: Any, expected: Any) -> bool:
    """Логика сравнения для where()/find()."""
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.casefold() in actual.casefold()
    if isinstance(expected, str) and actual is not None:
        return expected.casefold() in str(actual).casefold()
    return actual == expected


def build_columns(
    field: FormField,
    form_field: FormField | None,
) -> list[Column]:
    """Собрать список колонок таблицы.

    Источники (в порядке приоритета):
    1. Определение формы (``form_field.info["fields"]``) — полный список,
       включая колонки, пустые во всех строках.
    2. Существующие строки (union ячеек) — fallback, если формы нет.
    """
    columns: list[Column] = []
    seen: set[int] = set()

    # 1. Из определения формы (info["fields"])
    if form_field is not None and isinstance(form_field.info, dict):
        for sub in form_field.info.get("fields", []) or []:
            if not isinstance(sub, dict):
                continue
            cid = sub.get("id")
            if cid is None or cid in seen:
                continue
            seen.add(cid)
            columns.append(
                Column(id=cid, name=sub.get("name") or f"col#{cid}", type=sub.get("type"))
            )

    # 2. Fallback / дополнение из строк задачи
    rows = field.as_table_rows()
    for tr in rows:
        for cell in tr.cells:
            if cell.id in seen:
                continue
            seen.add(cell.id)
            columns.append(
                Column(
                    id=cell.id,
                    name=cell.name or f"col#{cell.id}",
                    type=cell.type.value if cell.type else None,
                )
            )
    return columns


def build_rows(table: TableProxy, field: FormField) -> list[Row]:
    """Построить строки-прокси из значения table-поля."""
    rows: list[Row] = []
    for tr in field.as_table_rows():
        cells_by_id = {cell.id: cell for cell in tr.cells}
        rows.append(Row(table, row_id=tr.row_id, cells=cells_by_id, position=tr.position))
    return rows
