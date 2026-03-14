# tests/test_handlers.py — Тесты для handlers/pyrogram_handlers.py

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.ext import ConversationHandler

from handlers.pyrogram_handlers import (
    CONNECT_PHONE,
    on_connect,
    on_connect_cancel,
    on_disconnect,
    on_status,
    on_pyrogram_message,
    on_pyrogram_draft,
    update_menu_language,
)


class TestOnConnect:
    """Тесты для on_connect()."""

    @pytest.mark.asyncio
    async def test_already_connected(self, mock_update, mock_context):
        """Если уже подключён → сообщение + END."""
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc:
            mock_pc.is_active.return_value = True

            result = await on_connect(mock_update, mock_context)

        assert result == ConversationHandler.END
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_connection(self, mock_update, mock_context):
        """Новое подключение → возвращает CONNECT_PHONE."""
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc:
            mock_pc.is_active.return_value = False

            result = await on_connect(mock_update, mock_context)

        assert result == CONNECT_PHONE
        mock_update.message.reply_text.assert_called_once()


class TestOnConnectCancel:
    """Тесты для on_connect_cancel()."""

    @pytest.mark.asyncio
    async def test_clears_context_and_ends(self, mock_update, mock_context):
        mock_context.user_data = {
            "pyrogram_client": MagicMock(),
            "phone": "+123",
            "phone_code_hash": "abc",
        }

        result = await on_connect_cancel(mock_update, mock_context)

        assert result == ConversationHandler.END
        assert "pyrogram_client" not in mock_context.user_data
        assert "phone" not in mock_context.user_data


class TestOnDisconnect:
    """Тесты для on_disconnect()."""

    @pytest.mark.asyncio
    async def test_not_connected(self, mock_update, mock_context):
        """Не подключён → сообщение 'not connected'."""
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc:
            mock_pc.is_active.return_value = False

            await on_disconnect(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        # stop_listening не должен вызываться
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc2:
            mock_pc2.stop_listening.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnects(self, mock_update, mock_context):
        """Подключён → отключает и очищает сессию."""
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.pyrogram_handlers.clear_session", new_callable=AsyncMock) as mock_clear:
            mock_pc.is_active.return_value = True
            mock_pc.stop_listening = AsyncMock()

            await on_disconnect(mock_update, mock_context)

        mock_pc.stop_listening.assert_called_once_with(mock_update.effective_user.id)
        mock_clear.assert_called_once_with(mock_update.effective_user.id)


class TestOnStatus:
    """Тесты для on_status()."""

    @pytest.mark.asyncio
    async def test_connected_status(self, mock_update, mock_context):
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc:
            mock_pc.is_active.return_value = True

            await on_status(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnected_status(self, mock_update, mock_context):
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc:
            mock_pc.is_active.return_value = False

            await on_status(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()


class TestOnPyrogramMessage:
    """Тесты для on_pyrogram_message()."""

    @pytest.mark.asyncio
    async def test_no_text_returns_early(self):
        """Сообщение без текста → ранний return."""
        message = MagicMock()
        message.text = None

        await on_pyrogram_message(123, MagicMock(), message)

    @pytest.mark.asyncio
    async def test_outgoing_returns_early(self):
        """Исходящее сообщение → ранний return."""
        message = MagicMock()
        message.text = "Hello"
        message.outgoing = True

        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc:
            mock_pc.read_chat_history = AsyncMock()

            await on_pyrogram_message(123, MagicMock(), message)

        mock_pc.read_chat_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_message_returns_early(self):
        """Сообщение от бота → ранний return."""
        message = MagicMock()
        message.text = "Hello"
        message.outgoing = False
        message.from_user = MagicMock()
        message.from_user.is_bot = True

        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc:
            mock_pc.read_chat_history = AsyncMock()

            await on_pyrogram_message(123, MagicMock(), message)

        mock_pc.read_chat_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_generates_and_sets_draft(self):
        """Генерирует ответ и устанавливает черновик."""
        message = MagicMock()
        message.text = "Hello"
        message.outgoing = False
        message.from_user = MagicMock()
        message.from_user.is_bot = False
        message.from_user.first_name = "Test"
        message.chat = MagicMock()
        message.chat.id = 456

        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.pyrogram_handlers.generate_reply", new_callable=AsyncMock) as mock_gen:
            mock_pc.read_chat_history = AsyncMock(return_value=[
                {"role": "other", "text": "Hello"}
            ])
            mock_pc.set_draft = AsyncMock(return_value=True)
            mock_gen.return_value = "Hi there!"

            await on_pyrogram_message(123, MagicMock(), message)

        mock_gen.assert_called_once()
        mock_pc.set_draft.assert_called_once_with(123, 456, "Hi there!")


class TestOnPyrogramDraft:
    """Тесты для on_pyrogram_draft()."""

    @pytest.mark.asyncio
    async def test_without_trigger_suffix(self):
        """Без суффикса 🦉 → ранний return."""
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc:
            mock_pc.read_chat_history = AsyncMock()

            await on_pyrogram_draft(123, 456, "normal text")

        mock_pc.read_chat_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_instruction(self):
        """Суффикс без инструкции → ранний return."""
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc:
            mock_pc.read_chat_history = AsyncMock()

            await on_pyrogram_draft(123, 456, "🦉")

        mock_pc.read_chat_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_instruction(self):
        """С суффиксом 🦉 → читает историю, генерирует, ставит черновик."""
        with patch("handlers.pyrogram_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.pyrogram_handlers.generate_response", new_callable=AsyncMock) as mock_gen:
            mock_pc.read_chat_history = AsyncMock(return_value=[
                {"role": "user", "text": "Привет"},
            ])
            mock_pc.set_draft = AsyncMock(return_value=True)
            mock_gen.return_value = "Сгенерированный ответ"

            await on_pyrogram_draft(123, 456, "ответь формально🦉")

        mock_pc.read_chat_history.assert_called_once()
        mock_gen.assert_called_once()
        mock_pc.set_draft.assert_called_once_with(123, 456, "Сгенерированный ответ")


class TestUpdateMenuLanguage:
    """Тесты для update_menu_language()."""

    @pytest.mark.asyncio
    async def test_english_returns_early(self, mock_bot):
        """Английский → ранний return (уже по умолчанию)."""
        await update_menu_language(mock_bot, "en")
        mock_bot.set_my_commands.assert_not_called()

    @pytest.mark.asyncio
    async def test_sets_commands_for_other_language(self, mock_bot):
        """Другой язык → устанавливает команды."""
        with patch(
            "handlers.pyrogram_handlers.get_system_messages",
            new_callable=AsyncMock,
            return_value={
                "menu_start": "Начать",
                "menu_connect": "Подключить",
                "menu_connectqr": "QR",
                "menu_disconnect": "Отключить",
                "menu_status": "Статус",
            },
        ):
            await update_menu_language(mock_bot, "ru")

        mock_bot.set_my_commands.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_language_treated_as_english(self, mock_bot):
        await update_menu_language(mock_bot, None)
        mock_bot.set_my_commands.assert_not_called()
