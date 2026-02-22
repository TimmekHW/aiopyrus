"""Extended tests for webhook server — run_app coverage."""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web

from aiopyrus.bot.webhook.server import run_app


class TestRunApp:
    async def test_run_app_starts_and_cleans_up(self):
        """run_app sets up runner, starts site, waits, then cleans up on cancel."""
        app = web.Application()

        mock_runner = MagicMock()
        mock_runner.setup = AsyncMock()
        mock_runner.cleanup = AsyncMock()

        mock_site = MagicMock()
        mock_site.start = AsyncMock()

        mock_event = MagicMock()
        mock_event.wait = AsyncMock(side_effect=asyncio.CancelledError())

        with (
            patch("aiopyrus.bot.webhook.server.web.AppRunner", return_value=mock_runner),
            patch("aiopyrus.bot.webhook.server.web.TCPSite", return_value=mock_site),
            patch("asyncio.Event", return_value=mock_event),
            contextlib.suppress(asyncio.CancelledError),
        ):
            await run_app(app, host="127.0.0.1", port=9999)

        mock_runner.setup.assert_called_once()
        mock_site.start.assert_called_once()
        mock_runner.cleanup.assert_called_once()
