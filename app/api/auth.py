"""Telegram Mini App initData HMAC-SHA256 validation."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl, unquote

LOGGER = logging.getLogger(__name__)


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    Validate Telegram WebApp initData string.

    Returns parsed user dict on success, None on failure.
    Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    try:
        params = dict(parse_qsl(init_data, strict_parsing=True))
    except Exception:
        return None

    hash_value = params.pop("hash", None)
    if not hash_value:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))

    # secret_key = HMAC-SHA256("WebAppData", bot_token)
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode(),
        digestmod=hashlib.sha256,
    ).digest()
    expected = hmac.new(
        key=secret_key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, hash_value):
        LOGGER.warning("initData HMAC mismatch — rejecting request")
        return None

    auth_ts = int(params.get("auth_date", 0))
    if not auth_ts or (time.time() - auth_ts) > 86400:
        LOGGER.warning("initData expired or missing auth_date — rejecting request")
        return None

    user_str = params.get("user")
    if not user_str:
        return None

    try:
        return json.loads(unquote(user_str))
    except Exception:
        LOGGER.warning("initData user field is not valid JSON")
        return None
