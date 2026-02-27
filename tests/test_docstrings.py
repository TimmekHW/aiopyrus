"""Verify all public methods/classes have docstrings — documentation quality gate."""

from __future__ import annotations

import inspect

import pytest

from aiopyrus.bot.bot import PyrusBot
from aiopyrus.user.client import UserClient
from aiopyrus.utils.context import TaskContext


def _public_methods(cls: type) -> list[tuple[str, object]]:
    """Return (name, method) for all public non-dunder methods of *cls*."""
    return [
        (name, obj)
        for name, obj in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]


def _public_properties(cls: type) -> list[tuple[str, object]]:
    """Return (name, property) for all public properties of *cls*."""
    return [
        (name, obj)
        for name, obj in inspect.getmembers(cls)
        if isinstance(obj, property) and not name.startswith("_")
    ]


# -- UserClient methods --


class TestUserClientDocstrings:
    @pytest.mark.parametrize(
        "name,method",
        _public_methods(UserClient),
        ids=[n for n, _ in _public_methods(UserClient)],
    )
    def test_method_has_docstring(self, name: str, method: object):
        doc = getattr(method, "__doc__", None)
        assert doc and doc.strip(), f"UserClient.{name}() has no docstring"


# -- TaskContext methods & properties --


class TestTaskContextDocstrings:
    @pytest.mark.parametrize(
        "name,method",
        _public_methods(TaskContext),
        ids=[n for n, _ in _public_methods(TaskContext)],
    )
    def test_method_has_docstring(self, name: str, method: object):
        doc = getattr(method, "__doc__", None)
        assert doc and doc.strip(), f"TaskContext.{name}() has no docstring"

    @pytest.mark.parametrize(
        "name,prop",
        _public_properties(TaskContext),
        ids=[n for n, _ in _public_properties(TaskContext)],
    )
    def test_property_has_docstring(self, name: str, prop: object):
        doc = getattr(prop, "__doc__", None)
        assert doc and doc.strip(), f"TaskContext.{name} property has no docstring"


# -- PyrusBot methods --


class TestPyrusBotDocstrings:
    @pytest.mark.parametrize(
        "name,method",
        _public_methods(PyrusBot),
        ids=[n for n, _ in _public_methods(PyrusBot)],
    )
    def test_method_has_docstring(self, name: str, method: object):
        doc = getattr(method, "__doc__", None)
        assert doc and doc.strip(), f"PyrusBot.{name}() has no docstring"
