import asyncio

from app.handlers.start import cmd_start
from tests.fakes import FakeMessage
from tests.helpers import assert_contains, extract_last_text, last_outgoing


def test_start_denied(config_denied, user_denied):
    message = FakeMessage(user_id=user_denied)

    asyncio.run(cmd_start(message, config_denied))

    text = extract_last_text(message)
    assert_contains(text, ["Access denied"])


def test_start_authorized(config_admin, user_admin):
    message = FakeMessage(user_id=user_admin)

    asyncio.run(cmd_start(message, config_admin))

    last = last_outgoing(message)
    assert last is not None
    assert_contains(last["text"], ["Welcome", "menu"])
    assert last["reply_markup"] is not None
