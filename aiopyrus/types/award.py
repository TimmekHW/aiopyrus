"""Awards API — модели наград сотрудников (Pyrus v1.22+).

API наград — пороги выдачи/отзыва, счётчики наград у участников.

Note:
    Awards API доступен только в современных сборках Pyrus (cloud и
    свежий on-premise).  На legacy on-premise эндпоинты могут вернуть
    202 «No HTTP resource was found» — это знак того, что фича не
    развёрнута.  См. :meth:`UserClient.get_award_threshold` и
    последующие.
"""

from __future__ import annotations

from datetime import datetime

from .base import PyrusModel


class AwardThreshold(PyrusModel):
    """Пороги выдачи и отзыва награды.

    ``grant_threshold`` — сколько событий нужно, чтобы выдать награду.
    ``revoke_threshold`` — сколько подряд «провалов», чтобы её отозвать.
    Если оба ненулевые, ``revoke_threshold`` должен быть строго больше
    ``grant_threshold``.
    """

    grant_threshold: int = 0
    revoke_threshold: int = 0


class MemberAwardCounter(PyrusModel):
    """Текущий счётчик награды у сотрудника."""

    person_id: int
    award_id: int
    award_counter: int = 0
    assignment_date: datetime | None = None
