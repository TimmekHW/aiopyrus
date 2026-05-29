"""Knowledge Base API — модели (Pyrus 2026, v1.24).

База знаний Pyrus — статьи и темы (topics) с разрешениями.

Важная особенность: ``id`` элементов базы знаний — **строки**, а не
числа (напр., ``"BxqPU8UrjlC"``).  Все сигнатуры используют ``str``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from .base import PyrusModel
from .user import Person


class KnowledgeBaseAttachment(PyrusModel):
    """Файл, прикреплённый к статье базы знаний."""

    id: str  # GUID, не int
    name: str
    size: int | None = None
    url: str | None = None


class KnowledgeBaseStructureNode(PyrusModel):
    """Узел в иерархии базы знаний — статья или тема.

    Возвращается из ``GET /knowledgebase/structure``. У темы (``topic``)
    в поле ``children`` лежат вложенные узлы. У статьи (``article``)
    ``children`` обычно пустой.

    Note:
        ``access_right`` — свободный ``str`` для forward-compat. На
        prod встречаются значения ``"read"``, ``"write"``, ``"none"``
        (доки про ``"none"`` не упоминают — а прод сильнее доков).
    """

    id: str
    type: Literal["article", "topic"]
    title: str = ""
    parent_topic_id: str | None = None
    access_right: str | None = None
    is_open_for_organization: bool | None = None
    children: list[KnowledgeBaseStructureNode] = []


KnowledgeBaseStructureNode.model_rebuild()


class KnowledgeBaseStructure(PyrusModel):
    """Ответ ``GET /knowledgebase/structure`` — корень иерархии БЗ.

    Pyrus может опускать ``parent_topic_id`` и ``depth``, если запрос
    был без параметров.
    """

    parent_topic_id: str | None = None
    depth: int | None = None
    items: list[KnowledgeBaseStructureNode] = []


class KnowledgeBaseItem(PyrusModel):
    """Элемент базы знаний — статья (article) или тема (topic).

    Используется для GET / POST / PUT ``/knowledgebase[/{id}]``.

    Note:
        У темы (``type="topic"``) поле ``body`` обычно ``None``.
        У статьи (``type="article"``) поле ``body`` обязательно при
        создании — содержит Markdown-текст.
    """

    id: str
    title: str = ""
    type: Literal["article", "topic"] | None = None
    body: str | None = None  # Markdown; None для topic
    author: Person | None = None
    parent_topic_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_edited_by: Person | None = None
    version: int | None = None
    access_right: str | None = None  # see KnowledgeBaseStructureNode
    is_open_for_organization: bool | None = None
    is_public: bool | None = None
    attachments: list[KnowledgeBaseAttachment] | None = None


class KnowledgeBasePermissions(PyrusModel):
    """Разрешения элемента БЗ.

    Возвращается из ``GET /knowledgebase/{id}/permissions``.

    Note:
        Запрос на изменение принимает ``list[int]`` (ID людей), а ответ
        возвращает ``list[Person]`` (объекты целиком). Эта асимметрия —
        особенность API Pyrus.
    """

    global_permission: str | None = None  # "read" / "write" / "none"
    inherit: bool | None = None
    readers: list[Person] = []
    editors: list[Person] = []
