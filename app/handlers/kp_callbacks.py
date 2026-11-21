"""Buttons of the КП server (kp-helperAI, Oracle): callback_data "kp:<service>:..." (owner 2026-11-21).

The КП server sends its messages to the owner with this bot's token (send-only), so Telegram delivers their button
presses here. We only check it is the owner, forward the press to the server's gateway signed with
KP_GATEWAY_SECRET (header X-KP-Signature = HMAC-SHA256(secret, ts + "." + body), X-KP-Timestamp = ts) and show its
short answer. The server does the work and edits the message itself. Config: KP_GATEWAY_URL, KP_GATEWAY_SECRET.
"""
import hashlib
import hmac
import json
import logging
import time

import aiohttp
from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config import Config
from app.utils.telegram import is_owner_callback, safe_query_answer

LOGGER = logging.getLogger(__name__)
router = Router()


def sign(secret: str, ts: str, body: bytes) -> str:
    return hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()


@router.callback_query(F.data.startswith("kp:"))
async def cb_kp(query: CallbackQuery, config: Config) -> None:
    if not is_owner_callback(query, config):
        await safe_query_answer(query, "⛔ Немає доступу", show_alert=True)
        return
    if not config.kp_gateway_url or not config.kp_gateway_secret:
        await safe_query_answer(query, "КП-сервер не настроен", show_alert=True)
        return
    msg = query.message
    body = json.dumps({"data": query.data, "user_id": query.from_user.id,
                       "chat_id": msg.chat.id if msg else None,
                       "message_id": msg.message_id if msg else None}).encode()
    ts = str(int(time.time()))
    headers = {"Content-Type": "application/json", "X-KP-Timestamp": ts,
               "X-KP-Signature": sign(config.kp_gateway_secret, ts, body)}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            async with session.post(config.kp_gateway_url, data=body, headers=headers) as resp:
                if resp.status == 200:
                    answer = (await resp.json()).get("toast", "")
                else:
                    LOGGER.warning("kp gateway answered %s for %s", resp.status, query.data)
                    answer = f"КП-сервер: ошибка {resp.status}"
    except Exception:
        LOGGER.exception("kp gateway unreachable")
        answer = "КП-сервер не отвечает, попробуй позже"
    await safe_query_answer(query, answer)
