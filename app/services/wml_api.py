"""JSON API client for the WML CRM (wml.pp.ua/api) — orders and monthly file counts.

Separate from `wml_client` (HTML scraper): this one writes. Same account
(WML_USERNAME / WML_PASSWORD). The token is fetched on first use and again on
a 401. Synchronous (requests) — call through asyncio.to_thread.

Orders are "content requests"; monthly file counts are "content request files"
(create is an upsert by profile + month on the CRM side).
"""
import logging
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)

API_URL = "https://wml.pp.ua/api"
_TIMEOUT = 20
_CALL_TIMEOUT = 60  # evening peaks on the CRM side hit 20 s

# Order types the CRM accepts — sent by name, same spelling as Notion's `type`
ORDER_TYPES = ("ad request", "custom", "short", "call", "verif reddit")


class WmlApiError(RuntimeError):
    pass


class WmlApi:
    def __init__(self, username: str, password: str, session: requests.Session | None = None) -> None:
        self._username = username
        self._password = password
        self._session = session or requests.Session()
        self._token: str | None = None

    def _login(self) -> None:
        resp = self._session.post(
            f"{API_URL}/login",
            json={"username": self._username, "password": self._password},
            timeout=_TIMEOUT,
        )
        data = self._json(resp)
        if not data.get("success") or not data.get("token"):
            raise WmlApiError(f"WML login failed (HTTP {resp.status_code})")
        self._token = data["token"]

    @staticmethod
    def _json(resp: requests.Response) -> dict[str, Any]:
        try:
            return resp.json()
        except ValueError:
            raise WmlApiError(f"WML API: non-JSON response (HTTP {resp.status_code})")

    def _call(self, method: str, path: str, payload: dict[str, Any], retry_on_timeout: bool = False) -> dict[str, Any]:
        """`retry_on_timeout` only for idempotent calls: a timed-out request may still have been applied."""
        if self._token is None:
            self._login()
        relogged = False
        attempts = 2 if retry_on_timeout else 1
        attempt = 0
        while True:
            try:
                resp = self._session.request(
                    method,
                    f"{API_URL}{path}",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=_CALL_TIMEOUT,
                )
            except (requests.Timeout, requests.ConnectionError):
                attempt += 1
                if attempt >= attempts:
                    raise
                LOGGER.warning("WML API %s %s timed out, retrying once", method, path)
                continue
            if resp.status_code == 401 and not relogged:
                self._login()  # token expired — once
                relogged = True
                continue
            if resp.status_code == 401:
                raise WmlApiError(f"WML API {method} {path}: unauthorized after re-login")
            data = self._json(resp)
            if resp.status_code >= 400 or not data.get("success"):
                raise WmlApiError(f"WML API {method} {path}: HTTP {resp.status_code}: {str(data)[:200]}")
            return data

    def create_order(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Create a content request. Required: profile, title, in, type; optional: out, count, received.
        The returned `id` is needed for later updates."""
        return self._call("POST", "/content-request", fields)

    def update_order(self, request_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        """Update out / count / received of an existing content request."""
        return self._call("POST", f"/content-request/{request_id}", fields, retry_on_timeout=True)

    def upsert_files(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Create or update a model's monthly file counts (profile + month identify the row)."""
        return self._call("POST", "/content-request-files", fields, retry_on_timeout=True)
