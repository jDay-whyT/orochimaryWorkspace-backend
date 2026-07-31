"""Tests for app/api/auth.py — Telegram Mini App initData HMAC validation.

Previously had zero test coverage despite being the sole authentication
mechanism for every /api/scout/* endpoint (see [[project_security_review_jul2026]]).
"""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.api.auth import validate_init_data

BOT_TOKEN = "123456:test-bot-token"


def _signed_init_data(user: dict, bot_token: str = BOT_TOKEN, auth_date: int | None = None,
                       extra: dict | None = None) -> str:
    """Build a validly-signed initData string the same way Telegram does."""
    params = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "user": json.dumps(user, separators=(",", ":")),
    }
    if extra:
        params.update(extra)
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


class TestValidateInitData:
    def test_valid_signature_returns_user_dict(self):
        init_data = _signed_init_data({"id": 42, "username": "scout1"})
        user = validate_init_data(init_data, BOT_TOKEN)
        assert user == {"id": 42, "username": "scout1"}

    def test_wrong_bot_token_rejected(self):
        init_data = _signed_init_data({"id": 42, "username": "scout1"})
        assert validate_init_data(init_data, "999999:different-token") is None

    def test_tampered_user_field_rejected(self):
        init_data = _signed_init_data({"id": 42, "username": "scout1"})
        # Attacker swaps their own id in after signing — hash no longer matches.
        tampered = init_data.replace("%22id%22%3A42", "%22id%22%3A999")
        assert validate_init_data(tampered, BOT_TOKEN) is None

    def test_missing_hash_rejected(self):
        init_data = "auth_date=123&user=%7B%7D"
        assert validate_init_data(init_data, BOT_TOKEN) is None

    def test_expired_auth_date_rejected(self):
        old_ts = int(time.time()) - 90000  # > 86400s old
        init_data = _signed_init_data({"id": 1}, auth_date=old_ts)
        assert validate_init_data(init_data, BOT_TOKEN) is None

    def test_missing_auth_date_rejected(self):
        params = {"user": json.dumps({"id": 1})}
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        params["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        assert validate_init_data(urlencode(params), BOT_TOKEN) is None

    def test_missing_user_field_rejected(self):
        params = {"auth_date": str(int(time.time()))}
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        params["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        assert validate_init_data(urlencode(params), BOT_TOKEN) is None

    def test_malformed_query_string_rejected(self):
        assert validate_init_data("not a valid=query&&string=%", BOT_TOKEN) is None

    def test_non_json_user_field_rejected(self):
        init_data = _signed_init_data({"id": 1})
        # Re-sign with a non-JSON user value.
        params = {"auth_date": str(int(time.time())), "user": "not-json"}
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        params["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        assert validate_init_data(urlencode(params), BOT_TOKEN) is None
