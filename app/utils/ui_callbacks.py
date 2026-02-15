from dataclasses import dataclass


UI_PREFIX = "ui:"


@dataclass(frozen=True)
class UICallback:
    module: str
    action: str
    value: str
    token: str


def build_ui_callback(module: str, action: str, value: str = "", token: str = "") -> str:
    payload = f"{UI_PREFIX}{module}:{action}"
    if value:
        payload = f"{payload}:{value}"
    return f"{payload}|{token}" if token else payload


def parse_ui_callback(data: str | None) -> UICallback | None:
    if not data or not data.startswith(UI_PREFIX):
        return None

    payload, _, token = data.partition("|")
    parts = payload.split(":")
    if len(parts) < 3:
        return None

    value = ":".join(parts[3:]) if len(parts) > 3 else ""
    return UICallback(
        module=parts[1],
        action=parts[2],
        value=value,
        token=token,
    )
