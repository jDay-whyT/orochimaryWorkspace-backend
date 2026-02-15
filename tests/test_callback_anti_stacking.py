from pathlib import Path


def test_no_direct_send_calls_in_callback_handlers():
    handlers_dir = Path('app/handlers')
    for path in handlers_dir.glob('*.py'):
        src = path.read_text(encoding='utf-8')
        if '@router.callback_query' not in src:
            continue
        assert '.message.answer(' not in src
        assert '.message.reply(' not in src
        assert 'bot.send_message(' not in src
