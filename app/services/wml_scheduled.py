"""Scheduled Notion -> WML CRM export (twice a day): orders and monthly file counts.

Notion is the source. Redis remembers what was last pushed, so only changes go out:
- orders without a CRM id (and `in` >= WML_EXPORT_FROM) are created; canceled ones never are;
- sent orders: changed out/count/received -> update; status Canceled -> "cancelled";
- a sent order that vanished from Notion: closed before -> archived at month close,
  leave the CRM alone; still open -> send "cancelled";
- file counts per model/month are upserted when they changed.

Sanity checks before anything goes out:
- file counts that went down or jumped by more than SPIKE_FILES are held once:
  sent on the next run only if still unchanged;
- counts that dropped to 0, models with two live Accounting records and Notion orders
  sharing one CRM id are not sent at all (warning every run until fixed);
- a profile the CRM does not know is reported once, then retried silently;
- a new month with nothing in it yet is not sent.

Until WML_EXPORT_APPLY=1 it only reports what it would do. Skipped while a month
close is in progress. Never raises.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from typing import Any

from aiogram import Bot

from app.config import Config
from app.services.month_close import CLOSE_IN_PROGRESS_KEY
from app.services.notion import NotionClient
from app.services.wml_api import WmlApi
from app.services.wml_export import order_payload, pick_files

LOGGER = logging.getLogger(__name__)

EXPORT_LOCK_KEY = "wml:export_lock"   # one export at a time (scheduler retry / manual run)
EXPORT_LOCK_SECONDS = 900
ORDER_STATE_KEY = "wml:order_state"   # hash: order page id -> last pushed state (json)
FILES_STATE_KEY = "wml:files_state"   # hash: "profile|month" -> last pushed payload (json)
MAX_VANISHED_CANCELS = 10             # more at once looks like an outage, not deletions
HELD_KEY = "wml:held"                 # hash: item key -> fingerprint held back on the last run
MISSING_PROFILES_KEY = "wml:missing_profiles"  # hash: profile -> 1, already reported as unknown
SPIKE_FILES = 300                     # a bigger jump of a model's monthly total between runs is suspicious
_FILE_FIELDS = ("of", "reddit", "twitter", "fansly", "request", "total")
_SEND_INTERVAL_SECONDS = 0.2

_TRACKED = ("out", "count", "received")


@dataclass
class ExportReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return not any((self.created, self.updated, self.cancelled, self.files, self.warnings, self.errors))


def _state(wml_id: int, fields: dict[str, Any], status: str, closed: bool) -> str:
    return json.dumps({"wml_id": wml_id, "fields": fields, "status": status, "closed": closed}, ensure_ascii=False)


async def _call(apply: bool, fn, *args) -> Any:
    if not apply:
        return None
    result = await asyncio.to_thread(fn, *args)
    await asyncio.sleep(_SEND_INTERVAL_SECONDS)
    return result


async def _hold_once(redis, apply: bool, key: str, fingerprint: str) -> bool:
    """True = hold this item now. The same item seen again unchanged next run is let through."""
    held = await redis.hget(HELD_KEY, key)
    if held == fingerprint:
        if apply:
            await redis.hdel(HELD_KEY, key)
        return False
    if apply:
        await redis.hset(HELD_KEY, key, fingerprint)
    return True


def _is_unknown_profile(error: Exception) -> bool:
    text = str(error).lower()
    return "profile not found" in text


async def _unknown_profile(redis, apply: bool, profile: str, report: ExportReport) -> None:
    """Report a profile the CRM doesn't know once; later runs retry it silently."""
    if await redis.hget(MISSING_PROFILES_KEY, profile):
        return
    if apply:
        await redis.hset(MISSING_PROFILES_KEY, profile, "1")
    report.warnings.append(f"{profile}: нет такого профиля в CRM — заведи его там, дальше пробую молча")


async def _known_profile(redis, apply: bool, profile: str) -> None:
    if apply:
        await redis.hdel(MISSING_PROFILES_KEY, profile)


async def export_orders(config: Config, notion: NotionClient, redis, api: WmlApi, apply: bool, report: ExportReport) -> None:
    orders = await notion.query_all_orders(config.db_orders)
    models = {m.page_id.replace("-", ""): m for m in await notion.query_all_models(config.db_models)}
    state = {k: json.loads(v) for k, v in (await redis.hgetall(ORDER_STATE_KEY) or {}).items()}
    seen: set[str] = set()

    by_wml_id: dict[int, list] = {}
    for order in orders:
        if order.wml_id is not None:
            by_wml_id.setdefault(order.wml_id, []).append(order)
    shared_ids = {wml_id for wml_id, group in by_wml_id.items() if len(group) > 1}
    for wml_id in sorted(shared_ids):
        titles = ", ".join(o.title for o in by_wml_id[wml_id])
        report.warnings.append(f"CRM id {wml_id} стоит у нескольких заказов ({titles}) — не отправляю, "
                               "оставь id только у одного")

    for order in orders:
        seen.add(order.page_id)
        if order.wml_id in shared_ids:
            continue
        model = models.get((order.model_id or "").replace("-", ""))
        canceled = (order.status or "").strip().lower() == "canceled"
        last = state.get(order.page_id)
        try:
            if order.wml_id is None and last and last.get("wml_id"):
                # created in the CRM earlier but its id never reached Notion: finish that, don't create again
                if apply:
                    await notion.set_order_wml_id(order.page_id, int(last["wml_id"]))
                continue
            if order.wml_id is None:
                payload, _ = order_payload(order, model)
                if payload is None or (order.in_date or "")[:10] < config.wml_export_from:
                    continue  # canceled / Tango / unknown type / before the export start
                try:
                    resp = await _call(apply, api.create_order, payload)
                except Exception as e:
                    if _is_unknown_profile(e):
                        await _unknown_profile(redis, apply, payload["profile"], report)
                        continue
                    raise
                await _known_profile(redis, apply, payload["profile"])
                if apply:
                    wml_id = int(resp["id"])
                    fields = {k: payload[k] for k in _TRACKED if k in payload}
                    # Redis first: if the Notion write fails, the next run finds the id here
                    await redis.hset(ORDER_STATE_KEY, order.page_id, _state(wml_id, fields, "active", "out" in payload))
                    await notion.set_order_wml_id(order.page_id, wml_id)
                report.created.append(order.title)
                continue

            if canceled:
                if not last or last.get("status") != "cancelled":
                    await _call(apply, api.update_order, order.wml_id, {"status": "cancelled"})
                    if apply:
                        await redis.hset(ORDER_STATE_KEY, order.page_id,
                                         _state(order.wml_id, (last or {}).get("fields", {}), "cancelled", False))
                    report.cancelled.append(order.title)
                continue

            payload, _ = order_payload(order, model)
            if payload is None:
                continue
            fields = {k: payload[k] for k in _TRACKED if k in payload}
            if last and last.get("fields") == fields and last.get("status") == "active":
                continue
            await _call(apply, api.update_order, order.wml_id, {**fields, "status": "active"})
            if apply:
                await redis.hset(ORDER_STATE_KEY, order.page_id, _state(order.wml_id, fields, "active", "out" in fields))
            if last:  # first sighting of an order sent by the test command is a silent re-sync
                report.updated.append(order.title)
        except Exception as e:
            LOGGER.exception("WML order export failed for %s", order.page_id)
            report.errors.append(f"{order.title}: {e}")

    # Orders that disappeared from Notion since the last push
    vanished_open = [(pid, st) for pid, st in state.items()
                     if pid not in seen and not st.get("closed") and st.get("status") != "cancelled"]
    vanished_done = [pid for pid, st in state.items() if pid not in seen and pid not in dict(vanished_open)]
    if len(vanished_open) > MAX_VANISHED_CANCELS:
        report.warnings.append(
            f"Из Notion пропало {len(vanished_open)} открытых заказов разом — отмены не отправляю, проверь вручную."
        )
    else:
        for pid, st in vanished_open:
            try:
                await _call(apply, api.update_order, st["wml_id"], {"status": "cancelled"})
                if apply:
                    await redis.hdel(ORDER_STATE_KEY, pid)
                report.cancelled.append(f"удалён из Notion (CRM id {st['wml_id']})")
            except Exception as e:
                report.errors.append(f"отмена CRM id {st['wml_id']}: {e}")
    if apply:
        for pid in vanished_done:  # archived at month close — the CRM keeps them as history
            await redis.hdel(ORDER_STATE_KEY, pid)


async def export_files(config: Config, notion: NotionClient, redis, api: WmlApi, apply: bool, report: ExportReport) -> None:
    batch = await pick_files(config, notion, datetime.now(config.timezone).strftime("%Y-%m"))
    for profile in batch.duplicates:
        report.warnings.append(f"{profile}: две живые записи в Accounting — файлы не отправляю, лишнюю удали")
    state = await redis.hgetall(FILES_STATE_KEY) or {}
    for _, payload in batch.items:
        key = f"{payload['profile']}|{payload['month']}"
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if state.get(key) == encoded:
            continue
        previous = json.loads(state[key]) if key in state else None
        if previous is None and payload["total"] == 0:
            continue  # nothing counted yet this month
        if previous and previous.get("total", 0) > 0 and payload["total"] == 0:
            report.warnings.append(f"{payload['profile']}: цифры обнулились ({batch.month}) — не отправляю")
            continue
        if previous:
            went_down = [f for f in _FILE_FIELDS if payload.get(f, 0) < previous.get(f, 0)]
            jump = payload["total"] - previous.get("total", 0)
            reason = None
            if went_down:
                reason = "уменьшилось " + ", ".join(f"{f} {previous.get(f, 0)}→{payload.get(f, 0)}" for f in went_down)
            elif jump > SPIKE_FILES:
                reason = f"скачок total {previous.get('total', 0)}→{payload['total']}"
            if reason and await _hold_once(redis, apply, f"files:{key}", encoded):
                report.warnings.append(f"{payload['profile']}: {reason} — задерживаю, "
                                       "если не поправят, отправлю в следующий раз")
                continue
        try:
            await _call(apply, api.upsert_files, payload)
            await _known_profile(redis, apply, payload["profile"])
            if apply:
                await redis.hset(FILES_STATE_KEY, key, encoded)
            report.files.append(f"{payload['profile']} ({payload['total']})")
        except Exception as e:
            if _is_unknown_profile(e):
                await _unknown_profile(redis, apply, payload["profile"], report)
                continue
            LOGGER.exception("WML files export failed for %s", payload["profile"])
            report.errors.append(f"{payload['profile']}: {e}")


def format_report(report: ExportReport, apply: bool) -> str:
    head = "📤 <b>Выгрузка в CRM</b>" if apply else "🔎 <b>Выгрузка в CRM — пока только отчёт</b> (включить: WML_EXPORT_APPLY=1)"
    lines = [head, ""]
    for title, items in (("Создать заказы", report.created), ("Обновить заказы", report.updated),
                         ("Отменить заказы", report.cancelled), ("Файлы моделей", report.files)):
        if items:
            shown = ", ".join(escape(i) for i in items[:8])
            more = f" …и ещё {len(items) - 8}" if len(items) > 8 else ""
            lines.append(f"<b>{title}: {len(items)}</b> — {shown}{more}")
    for w in report.warnings:
        lines.append(f"⚠️ {escape(w)}")
    if report.errors:
        lines.append(f"\n❌ Ошибки ({len(report.errors)}):")
        lines.extend(f"• {escape(e[:200])}" for e in report.errors[:10])
    text = "\n".join(lines)
    return text if len(text) <= 4000 else text[: text.rfind("\n", 0, 4000)] + "\n…"


async def push_orders_now(config: Config, notion: NotionClient, redis, api: WmlApi) -> ExportReport | None:
    """Send the current orders to the CRM right now (month close: before completed orders are deleted).

    Shares the scheduled export's lock so the two never run at once and create an order twice.
    None = nothing was sent (no Redis, or another export holds the lock).
    """
    if redis is None:
        return None
    if not await redis.set(EXPORT_LOCK_KEY, "1", nx=True, ex=EXPORT_LOCK_SECONDS):
        return None
    report = ExportReport()
    try:
        await export_orders(config, notion, redis, api, True, report)
    finally:
        await redis.delete(EXPORT_LOCK_KEY)
    return report


async def run_wml_export(bot: Bot, config: Config, notion: NotionClient, redis) -> None:
    """Scheduled entry point. Never raises; the owner gets one summary when anything happened."""
    if redis is None or not config.wml_username or not config.wml_password:
        LOGGER.warning("WML export skipped: Redis or WML credentials missing")
        return
    if await redis.get(CLOSE_IN_PROGRESS_KEY):
        LOGGER.info("WML export skipped: month close in progress")
        return
    if not await redis.set(EXPORT_LOCK_KEY, "1", nx=True, ex=EXPORT_LOCK_SECONDS):
        LOGGER.info("WML export skipped: another export is running")
        return
    apply = config.wml_export_apply
    api = WmlApi(config.wml_username, config.wml_password)
    report = ExportReport()
    try:
        for step in (export_orders, export_files):
            try:
                await step(config, notion, redis, api, apply, report)
            except Exception as e:
                LOGGER.exception("WML export step %s failed", step.__name__)
                report.errors.append(f"{step.__name__}: {e}")
    finally:
        await redis.delete(EXPORT_LOCK_KEY)
    if report.empty() or not config.owner_telegram_id:
        return
    try:
        await bot.send_message(config.owner_telegram_id, format_report(report, apply), parse_mode="HTML")
    except Exception:
        LOGGER.exception("Failed to send WML export report")
