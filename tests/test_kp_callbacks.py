"""kp: buttons: only the owner's presses are forwarded, signed, to the КП server gateway."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.handlers import kp_callbacks

OWNER = 5741158373


def query(user_id: int, data: str = "kp:o:no:3"):
    return SimpleNamespace(data=data, from_user=SimpleNamespace(id=user_id), answer=AsyncMock(),
                           message=SimpleNamespace(chat=SimpleNamespace(id=OWNER), message_id=42))


def config(url: str = "", secret: str = ""):
    return SimpleNamespace(owner_telegram_id=OWNER, kp_gateway_url=url, kp_gateway_secret=secret)


@pytest.mark.asyncio
async def test_owner_press_is_signed_and_forwarded():
    got = []

    async def handler(request):
        body = await request.read()
        got.append((json.loads(body), request.headers["X-KP-Signature"],
                    kp_callbacks.sign("s3cret", request.headers["X-KP-Timestamp"], body)))
        return web.json_response({"ok": True, "toast": "Принято"})

    app = web.Application()
    app.router.add_post("/kp/callback", handler)
    async with TestServer(app) as server:
        q = query(OWNER)
        await kp_callbacks.cb_kp(q, config(str(server.make_url("/kp/callback")), "s3cret"))
    payload, sig, expected = got[0]
    assert payload == {"data": "kp:o:no:3", "user_id": OWNER, "chat_id": OWNER, "message_id": 42}
    assert sig == expected
    q.answer.assert_awaited_once_with("Принято", show_alert=False)


@pytest.mark.asyncio
async def test_not_owner_and_not_configured_never_forward():
    q = query(1)
    await kp_callbacks.cb_kp(q, config("http://127.0.0.1:9/kp/callback", "s3cret"))
    assert q.answer.await_args.kwargs["show_alert"] is True
    q = query(OWNER)
    await kp_callbacks.cb_kp(q, config())
    assert "не настроен" in q.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_gateway_down_gives_a_short_answer():
    q = query(OWNER)
    await kp_callbacks.cb_kp(q, config("http://127.0.0.1:9/kp/callback", "s3cret"))
    assert "не отвечает" in q.answer.await_args.args[0]
