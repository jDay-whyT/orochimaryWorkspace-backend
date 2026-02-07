import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.state.memory import MemoryState


class TestDispatcherAccounting:
    """Dispatcher accounting flow tests."""

    @pytest.mark.asyncio
    async def test_custom_files_input_uses_accounting_service(self):
        from app.router.dispatcher import _handle_custom_files_input

        memory = MemoryState(ttl_seconds=60)
        user_state = {"model_id": "model-1", "model_name": "Test"}

        message = MagicMock()
        message.from_user.id = 7
        message.answer = AsyncMock()

        notion = AsyncMock()
        notion.create_accounting_record = AsyncMock()

        with patch("app.roles.is_editor", return_value=True), \
            patch("app.services.accounting.AccountingService") as svc_cls, \
            patch("app.services.model_card.build_model_card", return_value=("CARD", 0)), \
            patch("app.keyboards.inline.model_card_keyboard", return_value=MagicMock()), \
            patch("app.router.dispatcher.generate_token", return_value="tok"):
            svc_instance = svc_cls.return_value
            svc_instance.add_files = AsyncMock()

            await _handle_custom_files_input(
                message,
                "10",
                user_state,
                MagicMock(),
                notion,
                memory,
            )

            svc_instance.add_files.assert_called_once_with("model-1", 10)
            assert notion.create_accounting_record.call_count == 0
