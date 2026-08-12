from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from aiopyrus.bot.webhook.archive import save_raw_webhook
from aiopyrus.exceptions import PyrusWebhookSignatureError

if TYPE_CHECKING:
    from aiopyrus.bot.bot import PyrusBot
    from aiopyrus.bot.dispatcher import Dispatcher

log = logging.getLogger("aiopyrus.webhook")

# aiohttp's own default is 1 MiB — Pyrus occasionally sends webhooks larger
# than that (big tasks with many comments/fields), which silently became 413.
_DEFAULT_MAX_REQUEST_SIZE = 16 * 1024 * 1024  # 16 MiB


def create_app(
    *,
    dispatcher: Dispatcher,
    bot: PyrusBot,
    path: str = "/",
    verify_signature: bool = True,
    save_webhooks_dir: str | Path | None = None,
    max_request_size: int | None = None,
) -> web.Application:
    """Build an aiohttp Application for the Pyrus webhook endpoint.

    Parameters
    ----------
    save_webhooks_dir:
        If set, **every** incoming webhook (including retries and malformed
        bodies) is archived to this directory, one sub-folder per task id.
        ``None`` (default) disables archiving.
    max_request_size:
        Maximum accepted webhook body size in **bytes**. Bodies over the limit
        are rejected with HTTP 413 (Pyrus will retry 3 times, then drop the
        event). Default — 16 MiB. Pyrus rarely sends webhooks over 2 MiB, but
        it does happen on large tasks.

        Максимальный размер тела вебхука в **байтах**. Всё, что больше,
        отклоняется с HTTP 413 (Pyrus сделает 3 ретрая и бросит событие).
        По умолчанию — 16 МиБ. Не забудьте поднять лимит и на реверс-прокси
        (``client_max_body_size`` в nginx / Angie), если он стоит перед ботом.
    """

    size_limit = max_request_size or _DEFAULT_MAX_REQUEST_SIZE
    app = web.Application(client_max_size=size_limit)
    app["dispatcher"] = dispatcher
    app["bot"] = bot
    app["verify_signature"] = verify_signature
    app["save_webhooks_dir"] = save_webhooks_dir
    app["max_request_size"] = size_limit

    app.router.add_post(path, _webhook_handler)
    return app


async def _webhook_handler(request: web.Request) -> web.Response:
    dp: Dispatcher = request.app["dispatcher"]
    bot: PyrusBot = request.app["bot"]
    verify: bool = request.app["verify_signature"]

    try:
        raw_body = await request.read()
    except web.HTTPRequestEntityTooLarge:
        # Body exceeded client_max_size — make the 413 loud, not silent:
        # this is exactly the failure mode that is invisible in access logs.
        log.error(
            "Webhook body too large: Content-Length=%s exceeds max_request_size=%d bytes. "
            "Increase create_app(max_request_size=...) / start_webhook(max_request_size=...) "
            "and the reverse-proxy limit (nginx/Angie client_max_body_size).",
            request.headers.get("Content-Length", "?"),
            request.app["max_request_size"],
        )
        raise
    signature = request.headers.get("X-Pyrus-Sig", "")
    retry = request.headers.get("X-Pyrus-Retry", "")

    log.debug(
        "Webhook received: path=%s retry=%s body_len=%d",
        request.path,
        retry,
        len(raw_body),
    )

    # Archive EVERY incoming webhook (before parsing/validation) so even malformed
    # bodies and retries are preserved. One folder per task; never breaks handling.
    save_dir = request.app.get("save_webhooks_dir")
    if save_dir:
        try:
            _archive_payload = json.loads(raw_body)
        except Exception:
            _archive_payload = None
        await save_raw_webhook(
            save_dir,
            raw_body,
            _archive_payload,
            headers={
                "X-Pyrus-Sig": signature,
                "X-Pyrus-Retry": retry,
                "Content-Type": request.headers.get("Content-Type", ""),
            },
        )

    try:
        payload_data: dict = json.loads(raw_body)
    except json.JSONDecodeError:
        log.warning("Non-JSON webhook body received")
        return web.Response(status=400, text="Invalid JSON")

    try:
        response_data = await dp.process_webhook(
            payload_data,
            bot,
            verify_signature=verify,
            raw_body=raw_body,
            signature=signature,
        )
    except PyrusWebhookSignatureError as exc:
        log.warning("Signature verification failed: %s", exc)
        return web.Response(status=403, text="Forbidden")
    except Exception:
        log.exception("Unhandled error processing webhook")
        return web.Response(status=500, text="Internal Server Error")

    return web.json_response(response_data)


async def run_app(app: web.Application, *, host: str, port: int) -> None:
    """Run the aiohttp app (non-blocking version for embedding in asyncio loops)."""
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    log.info("Webhook server started at http://%s:%d", host, port)

    try:
        await asyncio.Event().wait()  # run forever
    finally:
        await runner.cleanup()
