# tests/test_poll_missed.py — Тесты для polling пропущенных сообщений

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.pyrogram_handlers import poll_missed_messages


def _make_incoming_msg(msg_id: int, text: str = "Привет", is_bot: bool = False):
    """Создаёт mock входящего сообщения."""
    msg = MagicMock()
    msg.id = msg_id
    msg.text = text
    msg.voice = None
    msg.sticker = None
    msg.outgoing = False
    msg.from_user = MagicMock()
    msg.from_user.is_bot = is_bot
    msg.from_user.first_name = "Test"
    msg.from_user.last_name = None
    msg.from_user.username = "test"
    msg.from_user.language_code = "en"
    msg.from_user.is_premium = False
    msg.chat = MagicMock()
    msg.chat.type = MagicMock(value="private")
    return msg


class TestPollMissedMessages:
    """Тесты для poll_missed_messages()."""

    @pytest.mark.asyncio
    async def test_no_active_client_returns_zero(self):
        """Без активного клиента → 0."""
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc:
            mock_pc._active_clients = {}
            mock_pc.is_active = MagicMock(return_value=False)
            result = await poll_missed_messages(999)

        assert result == 0

    @pytest.mark.asyncio
    async def test_finds_missed_message(self):
        """Пропущенное сообщение → вызывает on_pyrogram_message."""
        msg = _make_incoming_msg(100, "Пропущенное сообщение")
        msg.chat.id = 456

        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.pyrogram_handlers.on_pyrogram_message", new_callable=AsyncMock) as mock_handler, \
             patch("handlers.pyrogram_handlers._last_seen_msg_id", {}), \
             patch("handlers.pyrogram_handlers._reply_locks", {}), \
             patch("handlers.pyrogram_handlers._bot_drafts", {}):
            mock_client = MagicMock()
            mock_pc._active_clients = {123: mock_client}
            mock_pc.get_private_dialogs = AsyncMock(return_value=[456])
            mock_pc.get_last_incoming = AsyncMock(return_value=msg)

            result = await poll_missed_messages(123)

        assert result == 1
        mock_handler.assert_called_once_with(123, mock_client, msg)

    @pytest.mark.asyncio
    async def test_skips_already_seen_message(self):
        """Уже обработанное сообщение → пропускает."""
        msg = _make_incoming_msg(50)
        msg.chat.id = 456

        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.pyrogram_handlers.on_pyrogram_message", new_callable=AsyncMock) as mock_handler, \
             patch("handlers.pyrogram_handlers._last_seen_msg_id", {(123, 456): 50}), \
             patch("handlers.pyrogram_handlers._reply_locks", {}), \
             patch("handlers.pyrogram_handlers._bot_drafts", {}):
            mock_pc._active_clients = {123: MagicMock()}
            mock_pc.get_private_dialogs = AsyncMock(return_value=[456])
            mock_pc.get_last_incoming = AsyncMock(return_value=msg)

            result = await poll_missed_messages(123)

        assert result == 0
        mock_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_locked_chat(self):
        """Чат с активной генерацией → пропускает."""
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.pyrogram_handlers.on_pyrogram_message", new_callable=AsyncMock) as mock_handler, \
             patch("handlers.pyrogram_handlers._last_seen_msg_id", {}), \
             patch("handlers.pyrogram_handlers._reply_locks", {(123, 456): True}), \
             patch("handlers.pyrogram_handlers._bot_drafts", {}):
            mock_pc._active_clients = {123: MagicMock()}
            mock_pc.get_private_dialogs = AsyncMock(return_value=[456])
            mock_pc.get_last_incoming = AsyncMock()

            result = await poll_missed_messages(123)

        assert result == 0
        mock_handler.assert_not_called()
        mock_pc.get_last_incoming.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_bot_message(self):
        """Сообщение от бота → пропускает."""
        msg = _make_incoming_msg(100, is_bot=True)
        msg.chat.id = 456

        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.pyrogram_handlers.on_pyrogram_message", new_callable=AsyncMock) as mock_handler, \
             patch("handlers.pyrogram_handlers._last_seen_msg_id", {}), \
             patch("handlers.pyrogram_handlers._reply_locks", {}), \
             patch("handlers.pyrogram_handlers._bot_drafts", {}):
            mock_pc._active_clients = {123: MagicMock()}
            mock_pc.get_private_dialogs = AsyncMock(return_value=[456])
            mock_pc.get_last_incoming = AsyncMock(return_value=msg)

            result = await poll_missed_messages(123)

        assert result == 0
        mock_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_media_only_message(self):
        """Сообщение без текста/голоса/стикера → пропускает."""
        msg = _make_incoming_msg(100)
        msg.text = None
        msg.voice = None
        msg.sticker = None
        msg.chat.id = 456

        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.pyrogram_handlers.on_pyrogram_message", new_callable=AsyncMock) as mock_handler, \
             patch("handlers.pyrogram_handlers._last_seen_msg_id", {}), \
             patch("handlers.pyrogram_handlers._reply_locks", {}), \
             patch("handlers.pyrogram_handlers._bot_drafts", {}):
            mock_pc._active_clients = {123: MagicMock()}
            mock_pc.get_private_dialogs = AsyncMock(return_value=[456])
            mock_pc.get_last_incoming = AsyncMock(return_value=msg)

            result = await poll_missed_messages(123)

        assert result == 0
        mock_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_sticker_as_missed(self):
        """Стикер → считается пропущенным сообщением."""
        msg = _make_incoming_msg(100)
        msg.text = None
        msg.sticker = MagicMock(emoji="😊")
        msg.chat.id = 456

        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.pyrogram_handlers.on_pyrogram_message", new_callable=AsyncMock) as mock_handler, \
             patch("handlers.pyrogram_handlers._last_seen_msg_id", {}), \
             patch("handlers.pyrogram_handlers._reply_locks", {}), \
             patch("handlers.pyrogram_handlers._bot_drafts", {}):
            mock_client = MagicMock()
            mock_pc._active_clients = {123: mock_client}
            mock_pc.get_private_dialogs = AsyncMock(return_value=[456])
            mock_pc.get_last_incoming = AsyncMock(return_value=msg)

            result = await poll_missed_messages(123)

        assert result == 1
        mock_handler.assert_called_once()
