from __future__ import annotations

from typing import Iterable


def last_outgoing(message) -> dict | None:
    if not getattr(message, "outgoing", None):
        return None
    return message.outgoing[-1]


def extract_last_text(message) -> str:
    last = last_outgoing(message)
    if not last:
        return ""
    return last.get("text") or ""


def assert_contains(text: str, keywords: Iterable[str]) -> None:
    lowered = text.lower()
    for keyword in keywords:
        assert keyword.lower() in lowered, f"Expected '{keyword}' in '{text}'"


def assert_any_contains(actions: Iterable[dict], keywords: Iterable[str]) -> None:
    for action in actions:
        text = (action.get("text") or "").lower()
        if all(keyword.lower() in text for keyword in keywords):
            return
    expected = ", ".join(keywords)
    raise AssertionError(f"No action text contained keywords: {expected}")


def assert_called_with(mock, *expected_args, **expected_kwargs) -> None:
    if hasattr(mock, "await_args") and mock.await_args is not None:
        args, kwargs = mock.await_args
    else:
        args, kwargs = mock.call_args

    for index, expected in enumerate(expected_args):
        assert args[index] == expected, f"Arg {index} expected {expected}, got {args[index]}"

    for key, value in expected_kwargs.items():
        assert kwargs.get(key) == value, f"Kwarg {key} expected {value}, got {kwargs.get(key)}"

async def send(msg_factory, handler, text: str, *deps):
    msg = msg_factory(text=text)
    await handler(msg, *deps)
    return msg
