"""Тесты для v0.8.0: Knowledge Base, Awards, Telephony, новые поля User, ChannelType.max."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from aiopyrus.types.knowledge_base import (
    KnowledgeBaseItem,
    KnowledgeBasePermissions,
    KnowledgeBaseStructure,
    KnowledgeBaseStructureNode,
)
from aiopyrus.types.task import ChannelType
from aiopyrus.types.telephony import (
    CallMapping,
    Meeting,
    TelephonyMappingCode,
    TelephonyPersonRef,
)
from aiopyrus.types.user import Messenger, Person, SessionPolicy
from aiopyrus.user.client import UserClient

AUTH_URL = "https://accounts.pyrus.com/api/v4/auth"
API_BASE = "https://api.pyrus.com/v4/"


def _mock_auth() -> None:
    respx.post(AUTH_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "test", "api_url": API_BASE, "files_url": API_BASE},
        )
    )


@pytest.fixture
def client() -> UserClient:
    return UserClient(login="test@example.com", security_key="SECRET")


# ── ChannelType.max (VK MAX, добавлен в v1.23) ──────────────────────────────


class TestChannelTypeMax:
    def test_max_constant_exists(self):
        assert ChannelType.max.value == "max"

    def test_max_works_in_payload(self):
        assert str(ChannelType.max.value) == "max"


# ── Person: новые поля ───────────────────────────────────────────────────────


class TestPersonNewFields:
    def test_messenger_typed(self):
        p = Person.model_validate(
            {"id": 100500, "messenger": {"type": "Internet", "nickname": "kolbasenko"}}
        )
        assert isinstance(p.messenger, Messenger)
        assert p.messenger.type == "Internet"
        assert p.messenger.nickname == "kolbasenko"

    def test_messenger_extra_keys_ignored(self):
        """extra="ignore" сохраняет forward-compat для будущих ключей."""
        p = Person.model_validate(
            {
                "id": 100500,
                "messenger": {
                    "type": "Internet",
                    "nickname": "kolbasenko",
                    "future_key": "ok",
                },
            }
        )
        assert p.messenger is not None
        assert p.messenger.nickname == "kolbasenko"

    def test_organization_id(self):
        p = Person.model_validate({"id": 100500, "organization_id": 228173})
        assert p.organization_id == 228173

    def test_birth_date_dict(self):
        p = Person.model_validate({"id": 100500, "birth_date": {"day": 1, "month": 4}})
        assert p.birth_date == {"day": 1, "month": 4}

    def test_session_policy_six_fields(self):
        p = Person.model_validate(
            {
                "id": 100500,
                "mobile_session_settings": {"life_span_hours": 12, "max_count": 3},
                "web_session_inactive_settings": {"life_span_hours": 8, "max_count": 5},
            }
        )
        assert isinstance(p.mobile_session_settings, SessionPolicy)
        assert p.mobile_session_settings.life_span_hours == 12
        assert p.mobile_session_settings.max_count == 3
        assert isinstance(p.web_session_inactive_settings, SessionPolicy)
        assert p.web_session_inactive_settings.life_span_hours == 8


# ── Knowledge Base API ──────────────────────────────────────────────────────


class TestKnowledgeBase:
    @respx.mock
    async def test_get_structure_empty(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}knowledgebase/structure").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        await client.auth()
        kb = await client.get_knowledge_base_structure()
        assert isinstance(kb, KnowledgeBaseStructure)
        assert kb.items == []
        await client.close()

    @respx.mock
    async def test_get_structure_with_string_ids(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}knowledgebase/structure").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "BxqPU8UrjlC",
                            "type": "topic",
                            "title": "Корневая тема",
                            "access_right": "write",
                            "is_open_for_organization": True,
                            "children": [
                                {
                                    "id": "C5dcQ9vyrlD",
                                    "type": "article",
                                    "title": "Статья внутри темы",
                                    "parent_topic_id": "BxqPU8UrjlC",
                                    "access_right": "read",
                                    "is_open_for_organization": False,
                                    "children": [],
                                }
                            ],
                        }
                    ]
                },
            )
        )
        await client.auth()
        kb = await client.get_knowledge_base_structure()
        assert len(kb.items) == 1
        root = kb.items[0]
        assert root.id == "BxqPU8UrjlC"  # строковый ID
        assert root.type == "topic"
        assert len(root.children) == 1
        child = root.children[0]
        assert isinstance(child, KnowledgeBaseStructureNode)
        assert child.id == "C5dcQ9vyrlD"
        assert child.parent_topic_id == "BxqPU8UrjlC"
        assert child.access_right == "read"
        await client.close()

    @respx.mock
    async def test_get_item(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}knowledgebase/BxqPU8UrjlC").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "BxqPU8UrjlC",
                    "type": "article",
                    "title": "Заголовок",
                    "body": "# Markdown",
                    "version": 5,
                },
            )
        )
        await client.auth()
        item = await client.get_knowledge_base_item("BxqPU8UrjlC")
        assert isinstance(item, KnowledgeBaseItem)
        assert item.id == "BxqPU8UrjlC"
        assert item.body == "# Markdown"
        assert item.version == 5
        await client.close()

    async def test_create_article_without_body_raises(self, client: UserClient):
        with pytest.raises(ValueError, match="body is required"):
            await client.create_knowledge_base_item(title="X", type="article")
        await client.close()

    @respx.mock
    async def test_create_topic_no_body_ok(self, client: UserClient):
        _mock_auth()
        respx.post(f"{API_BASE}knowledgebase").mock(
            return_value=httpx.Response(
                200, json={"id": "new_topic", "type": "topic", "title": "Новая тема"}
            )
        )
        await client.auth()
        item = await client.create_knowledge_base_item(title="Новая тема", type="topic")
        assert item.id == "new_topic"
        await client.close()

    @respx.mock
    async def test_update_item_move_to_root(self, client: UserClient):
        """parent_topic_id=None + parent_topic_id_changed=True -> переместить в корень."""
        _mock_auth()
        route = respx.put(f"{API_BASE}knowledgebase/abc").mock(
            return_value=httpx.Response(200, json={"id": "abc", "type": "article", "title": "T"})
        )
        await client.auth()
        await client.update_knowledge_base_item(
            "abc", parent_topic_id=None, parent_topic_id_changed=True
        )
        sent = route.calls.last.request.content.decode()
        assert '"parent_topic_id":null' in sent or '"parent_topic_id": null' in sent
        assert '"parent_topic_id_changed":true' in sent or '"parent_topic_id_changed": true' in sent
        await client.close()

    @respx.mock
    async def test_delete_item(self, client: UserClient):
        _mock_auth()
        respx.delete(f"{API_BASE}knowledgebase/abc").mock(
            return_value=httpx.Response(200, json={"deleted": True})
        )
        await client.auth()
        ok = await client.delete_knowledge_base_item("abc")
        assert ok is True
        await client.close()

    @respx.mock
    async def test_get_permissions(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}knowledgebase/abc/permissions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "global_permission": "read",
                    "inherit": False,
                    "readers": [{"id": 100500, "first_name": "Данил", "last_name": "Колбасенко"}],
                    "editors": [],
                },
            )
        )
        await client.auth()
        perms = await client.get_knowledge_base_permissions("abc")
        assert isinstance(perms, KnowledgeBasePermissions)
        assert perms.global_permission == "read"
        assert perms.readers[0].full_name == "Данил Колбасенко"
        await client.close()


# ── Awards API ──────────────────────────────────────────────────────────────


class TestAwardsAPI:
    @respx.mock
    async def test_get_threshold(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}awards/7/threshold").mock(
            return_value=httpx.Response(200, json={"grant_threshold": 3, "revoke_threshold": 5})
        )
        await client.auth()
        t = await client.get_award_threshold(7)
        assert t.grant_threshold == 3
        assert t.revoke_threshold == 5
        await client.close()

    async def test_set_threshold_validates_order(self, client: UserClient):
        """revoke_threshold должен быть > grant_threshold (если оба ненулевые)."""
        with pytest.raises(ValueError, match="revoke_threshold must exceed"):
            await client.set_award_threshold(7, grant_threshold=5, revoke_threshold=3)
        await client.close()

    @respx.mock
    async def test_set_threshold_ok(self, client: UserClient):
        _mock_auth()
        respx.put(f"{API_BASE}awards/7/threshold").mock(
            return_value=httpx.Response(200, json={"grant_threshold": 3, "revoke_threshold": 5})
        )
        await client.auth()
        t = await client.set_award_threshold(7, grant_threshold=3, revoke_threshold=5)
        assert t.grant_threshold == 3
        await client.close()

    @respx.mock
    async def test_get_member_counter(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}members/100500/awards/7/counter").mock(
            return_value=httpx.Response(
                200,
                json={
                    "person_id": 100500,
                    "award_id": 7,
                    "award_counter": 3,
                    "assignment_date": "2026-05-29T10:00:00Z",
                },
            )
        )
        await client.auth()
        c = await client.get_member_award_counter(100500, 7)
        assert c.award_counter == 3
        assert c.person_id == 100500
        await client.close()

    @respx.mock
    async def test_increment_counter(self, client: UserClient):
        _mock_auth()
        respx.post(f"{API_BASE}members/100500/awards/7/counter/increment").mock(
            return_value=httpx.Response(
                200,
                json={"person_id": 100500, "award_id": 7, "award_counter": 4},
            )
        )
        await client.auth()
        c = await client.increment_member_award_counter(100500, 7)
        assert c.award_counter == 4
        await client.close()

    @respx.mock
    async def test_set_counter_via_query_param(self, client: UserClient):
        """value передаётся как ?value=N, а не в JSON-теле."""
        _mock_auth()
        route = respx.put(f"{API_BASE}members/100500/awards/7/counter").mock(
            return_value=httpx.Response(
                200,
                json={"person_id": 100500, "award_id": 7, "award_counter": 10},
            )
        )
        await client.auth()
        await client.set_member_award_counter(100500, 7, value=10)
        assert route.calls.last.request.url.params["value"] == "10"
        await client.close()


# ── Telephony API ───────────────────────────────────────────────────────────


class TestTelephonyAPI:
    @respx.mock
    async def test_register_call(self, client: UserClient):
        _mock_auth()
        respx.post(f"{API_BASE}integrations/call").mock(
            return_value=httpx.Response(
                200,
                json={
                    "task_id": 12345678,
                    "is_new_task": True,
                    "responsible_person": {
                        "user_id": "100500",  # сервер возвращает строкой
                        "first_name": "Данил",
                        "last_name": "Колбасенко",
                    },
                },
            )
        )
        await client.auth()
        resp = await client.register_call(
            account_id="acc1",
            from_number="+7901",
            to_number="+7902",
            mappings=[
                CallMapping(code=TelephonyMappingCode.call_duration, value=300),
                CallMapping(
                    code=TelephonyMappingCode.call_start_time,
                    value=datetime(2026, 5, 29, 10, 0, tzinfo=timezone.utc),
                ),
            ],
        )
        assert resp.task_id == 12345678
        assert isinstance(resp.responsible_person, TelephonyPersonRef)
        # validator привёл str → int
        assert resp.responsible_person.user_id == 100500
        await client.close()

    async def test_attach_call_record_validates_identifiers(self, client: UserClient):
        with pytest.raises(ValueError, match="task_id, external_id"):
            await client.attach_call_record(account_id="a", record_file="guid")
        await client.close()

    @respx.mock
    async def test_attach_call_record_with_task_id(self, client: UserClient):
        _mock_auth()
        respx.post(f"{API_BASE}integrations/attachcallrecord").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.auth()
        resp = await client.attach_call_record(account_id="a", record_file="guid", task_id=42)
        assert resp.error_code is None
        await client.close()

    def test_call_mapping_datetime_serializes_to_iso(self):
        m = CallMapping(
            code=TelephonyMappingCode.call_start_time,
            value=datetime(2026, 5, 29, 10, 0, tzinfo=timezone.utc),
        )
        dumped = m.model_dump()
        assert dumped["value"] == "2026-05-29T10:00:00Z"

    def test_call_mapping_int_passes_through(self):
        m = CallMapping(code=TelephonyMappingCode.call_duration, value=300)
        assert m.model_dump()["value"] == 300


# ── Meeting (для расширенного Calendar) ─────────────────────────────────────


class TestMeeting:
    def test_meeting_basic(self):
        m = Meeting.model_validate(
            {
                "id": 42,
                "type": "offline",
                "start_time": "2026-05-29T10:00:00Z",
                "duration": 60,
                "creator_id": 100500,
                "task_id": 12345678,
            }
        )
        assert m.id == 42
        assert m.duration == 60

    def test_meeting_with_join_parameters(self):
        m = Meeting.model_validate(
            {
                "id": 43,
                "type": "online",
                "start_time": "2026-05-29T10:00:00Z",
                "duration": 30,
                "creator_id": 100500,
                "task_id": 1,
                "join_parameters": {
                    "url": "https://meet.example.com/abc",
                    "password": "1234",
                },
            }
        )
        assert m.join_parameters is not None
        assert m.join_parameters.url == "https://meet.example.com/abc"


# ── New simple endpoints: get_role / delete_role / get_list / update_list ──


class TestRolesGetDelete:
    @respx.mock
    async def test_get_role(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}roles/42").mock(
            return_value=httpx.Response(
                200,
                json={"id": 42, "name": "Тестовая роль", "member_ids": [100500, 100501]},
            )
        )
        await client.auth()
        role = await client.get_role(42)
        assert role.id == 42
        assert role.name == "Тестовая роль"
        await client.close()

    @respx.mock
    async def test_delete_role_sends_body(self, client: UserClient):
        """DELETE с JSON-телом — особенность Pyrus."""
        _mock_auth()
        route = respx.delete(f"{API_BASE}roles/42").mock(
            return_value=httpx.Response(200, json={"deleted": True})
        )
        await client.auth()
        ok = await client.delete_role(42, task_receiver_id=100500)
        assert ok is True
        sent = route.calls.last.request.content.decode()
        assert '"task_receiver_id":100500' in sent or '"task_receiver_id": 100500' in sent
        await client.close()


class TestListsExtended:
    @respx.mock
    async def test_get_list(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}lists/42").mock(
            return_value=httpx.Response(
                200,
                json={"id": 42, "name": "Архив", "list_type": "private", "manager_ids": [100500]},
            )
        )
        await client.auth()
        lst = await client.get_list(42)
        assert lst.id == 42
        assert lst.list_type == "private"
        await client.close()

    @respx.mock
    async def test_get_list_tasks_rest(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}lists/42/tasks").mock(
            return_value=httpx.Response(
                200,
                json={"tasks": [{"id": 1}, {"id": 2}]},
            )
        )
        await client.auth()
        tasks = await client.get_list_tasks(42, item_count=10)
        assert len(tasks) == 2
        await client.close()

    @respx.mock
    async def test_get_list_tasks_empty_omits_key(self, client: UserClient):
        """Pyrus может опустить ключ tasks при пустом списке."""
        _mock_auth()
        respx.get(f"{API_BASE}lists/42/tasks").mock(
            return_value=httpx.Response(200, json={"has_more": False})
        )
        await client.auth()
        tasks = await client.get_list_tasks(42)
        assert tasks == []
        await client.close()

    @respx.mock
    async def test_update_list_metadata(self, client: UserClient):
        _mock_auth()
        route = respx.post(f"{API_BASE}lists/42").mock(
            return_value=httpx.Response(200, json={"id": 42, "name": "Новое имя"})
        )
        await client.auth()
        lst = await client.update_list(42, name="Новое имя", added_member_ids=[100500])
        assert lst.id == 42
        sent = route.calls.last.request.content.decode()
        assert '"name":"Новое имя"' in sent or '"name": "Новое имя"' in sent
        await client.close()


class TestCalendarNewParams:
    @respx.mock
    async def test_calendar_with_utc_params(self, client: UserClient):
        _mock_auth()
        route = respx.get(f"{API_BASE}calendar").mock(
            return_value=httpx.Response(200, json={"tasks": []})
        )
        await client.auth()
        await client.get_calendar(
            start_date_utc="2026-05-01T00:00:00Z",
            end_date_utc="2026-06-01T00:00:00Z",
            include_meetings=True,
        )
        url = route.calls.last.request.url
        assert url.params["start_date_utc"] == "2026-05-01T00:00:00Z"
        assert url.params["end_date_utc"] == "2026-06-01T00:00:00Z"
        assert url.params["include_meetings"] == "true"
        await client.close()

    @respx.mock
    async def test_calendar_legacy_from_date_deprecated(self, client: UserClient):
        """from_date бросает DeprecationWarning и маппится в start_date_utc."""
        _mock_auth()
        route = respx.get(f"{API_BASE}calendar").mock(
            return_value=httpx.Response(200, json={"tasks": []})
        )
        await client.auth()
        with pytest.warns(DeprecationWarning, match="from_date"):
            await client.get_calendar(from_date="2026-05-01")
        url = route.calls.last.request.url
        assert url.params["start_date_utc"] == "2026-05-01T00:00:00Z"
        await client.close()
