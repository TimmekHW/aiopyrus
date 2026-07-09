"""Тесты v0.9.2: ApprovalPendingFilter(any_step) + UserClient.find_pending_approvals."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from aiopyrus.bot.filters import ApprovalPendingFilter
from aiopyrus.types.task import Task
from aiopyrus.types.webhook import WebhookPayload
from aiopyrus.user.client import UserClient

AUTH_URL = "https://accounts.pyrus.com/api/v4/auth"
API_BASE = "https://api.pyrus.com/v4/"


def _task(
    current_step: int | None, approvals_by_step: dict[int, list[tuple[int, str | None]]]
) -> Task:
    """approvals_by_step: {step_num: [(person_or_role_id, choice|None), ...]}"""
    max_step = max(approvals_by_step) if approvals_by_step else 0
    approvals: list[list[dict[str, Any]]] = []
    for s in range(1, max_step + 1):
        entries: list[dict[str, Any]] = []
        for pid, choice in approvals_by_step.get(s, []):
            e: dict[str, Any] = {"person": {"id": pid, "first_name": f"P{pid}"}}
            if choice:
                e["approval_choice"] = choice
            entries.append(e)
        approvals.append(entries)
    return Task.model_validate(
        {"id": 1, "form_id": 321, "current_step": current_step, "approvals": approvals}
    )


async def _match(task: Task, ids: int | list[int], *, any_step: bool = False) -> bool:
    filt = ApprovalPendingFilter(ids, any_step=any_step)
    return bool(await filt(WebhookPayload(event="t", task_id=task.id, task=task)))


# ── ApprovalPendingFilter: несколько ID на текущем шаге (базовый OR) ─────────


class TestMultipleIdsCurrentStep:
    async def test_both_waiting_current_step(self):
        t = _task(2, {2: [(5555, "waiting"), (6666, "waiting")]})
        assert await _match(t, [5555, 6666]) is True
        assert await _match(t, [6666, 5555]) is True  # порядок не важен
        assert await _match(t, 5555) is True
        assert await _match(t, 6666) is True

    async def test_one_of_list_waiting(self):
        t = _task(2, {2: [(5555, "waiting")]})
        assert await _match(t, [5555, 6666]) is True  # 5555 ждёт
        assert await _match(t, [6666, 7777]) is False  # никто из списка

    async def test_approved_not_matched(self):
        t = _task(2, {2: [(5555, "approved"), (6666, "waiting")]})
        assert await _match(t, [5555]) is False  # уже approved
        assert await _match(t, [5555, 6666]) is True  # 6666 ещё ждёт


# ── any_step: approver на не-текущем шаге (главный фикс) ─────────────────────


class TestAnyStep:
    async def test_default_only_current_step(self):
        """По умолчанию approver на не-текущем шаге НЕ матчится."""
        t = _task(2, {2: [(5555, "waiting")], 3: [(6666, "waiting")]})
        assert await _match(t, [6666]) is False  # 6666 на шаге 3, тек = 2
        assert await _match(t, [5555]) is True  # 5555 на тек. шаге

    async def test_any_step_finds_other_steps(self):
        """any_step=True находит approver на любом шаге."""
        t = _task(2, {2: [(5555, "waiting")], 3: [(6666, "waiting")]})
        assert await _match(t, [6666], any_step=True) is True  # ждёт на ш.3
        assert await _match(t, [5555, 6666], any_step=True) is True

    async def test_any_step_still_respects_waiting(self):
        """any_step не матчит уже проголосовавших."""
        t = _task(2, {2: [(5555, "approved")], 3: [(6666, "approved")]})
        assert await _match(t, [5555, 6666], any_step=True) is False

    async def test_any_step_no_current_step_needed(self):
        """any_step работает даже когда current_step отсутствует (inbox-подобное)."""
        t = _task(None, {1: [(5555, "waiting")]})
        assert await _match(t, [5555]) is False  # без any_step нужен current_step
        assert await _match(t, [5555], any_step=True) is True

    async def test_no_approvals_false(self):
        t = Task.model_validate({"id": 1, "current_step": 1, "approvals": None})
        assert await _match(t, [5555], any_step=True) is False


# ── UserClient.find_pending_approvals (two-step реестр) ──────────────────────


def _mock_auth() -> None:
    respx.post(AUTH_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "t", "api_url": API_BASE, "files_url": API_BASE}
        )
    )


@pytest.fixture
def client() -> UserClient:
    return UserClient(login="test@example.com", security_key="SECRET")


class TestFindPendingApprovals:
    @respx.mock
    async def test_two_step_flow(self, client: UserClient):
        _mock_auth()
        # 1. Реестр формы 321 → две задачи (без approvals)
        respx.get(f"{API_BASE}forms/321/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 1001}, {"id": 1002}]})
        )
        # 2. Обогащение get_task
        respx.get(f"{API_BASE}tasks/1001").mock(
            return_value=httpx.Response(
                200,
                json={
                    "task": {
                        "id": 1001,
                        "current_step": 2,
                        "approvals": [
                            [],
                            [
                                {
                                    "person": {"id": 5555, "first_name": "R"},
                                    "approval_choice": "waiting",
                                }
                            ],
                        ],
                    }
                },
            )
        )
        respx.get(f"{API_BASE}tasks/1002").mock(
            return_value=httpx.Response(
                200,
                json={
                    "task": {
                        "id": 1002,
                        "current_step": 1,
                        "approvals": [
                            [
                                {
                                    "person": {"id": 9999, "first_name": "X"},
                                    "approval_choice": "waiting",
                                }
                            ],
                        ],
                    }
                },
            )
        )
        await client.auth()
        found = await client.find_pending_approvals(5555, forms=321)
        assert [t.id for t in found] == [1001]  # только 1001 ждёт 5555
        await client.close()

    @respx.mock
    async def test_any_step_in_helper(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}forms/321/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 2001}]})
        )
        # approver на шаге 3, текущий шаг 1
        respx.get(f"{API_BASE}tasks/2001").mock(
            return_value=httpx.Response(
                200,
                json={
                    "task": {
                        "id": 2001,
                        "current_step": 1,
                        "approvals": [
                            [],
                            [],
                            [
                                {
                                    "person": {"id": 6666, "first_name": "R"},
                                    "approval_choice": "waiting",
                                }
                            ],
                        ],
                    }
                },
            )
        )
        await client.auth()
        # any_step=True (дефолт helper'а) — найдёт на шаге 3
        found = await client.find_pending_approvals(6666, forms=321)
        assert [t.id for t in found] == [2001]
        # any_step=False — не найдёт (тек. шаг 1)
        found2 = await client.find_pending_approvals(6666, forms=321, any_step=False)
        assert found2 == []
        await client.close()

    @respx.mock
    async def test_empty_register(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}forms/321/register").mock(
            return_value=httpx.Response(200, json={"tasks": []})
        )
        await client.auth()
        found = await client.find_pending_approvals([5555, 6666], forms=321)
        assert found == []
        await client.close()
