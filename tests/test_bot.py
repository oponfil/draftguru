# tests/test_bot.py — Тесты для bot.py

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import on_start, on_text, on_error


class TestOnStart:
    """Тесты для on_start()."""

    @pytest.mark.asyncio
    async def test_upserts_user(self, mock_update, mock_context):
        """Сохраняет пользователя в БД."""
        with patch("bot.upsert_user", new_callable=AsyncMock) as mock_upsert, \
             patch("bot.update_tg_rating", new_callable=AsyncMock), \
             patch("bot.extract_rating_from_chat", return_value=None), \
             patch("bot.get_system_message", new_callable=AsyncMock, return_value="Hi!"), \
             patch("bot.update_menu_language", new_callable=AsyncMock):

            await on_start(mock_update, mock_context)

        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args[1]
        assert call_kwargs["user_id"] == mock_update.effective_user.id
        assert call_kwargs["username"] == mock_update.effective_user.username

    @pytest.mark.asyncio
    async def test_sends_greeting(self, mock_update, mock_context):
        """Отправляет приветствие на языке пользователя."""
        with patch("bot.upsert_user", new_callable=AsyncMock), \
             patch("bot.update_tg_rating", new_callable=AsyncMock), \
             patch("bot.extract_rating_from_chat", return_value=None), \
             patch("bot.get_system_message", new_callable=AsyncMock, return_value="Привет!"), \
             patch("bot.update_menu_language", new_callable=AsyncMock):

            await on_start(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_with("Привет!")

    @pytest.mark.asyncio
    async def test_updates_tg_rating(self, mock_update, mock_context):
        """Обновляет tg_rating через getChat."""
        with patch("bot.upsert_user", new_callable=AsyncMock), \
             patch("bot.update_tg_rating", new_callable=AsyncMock) as mock_rating, \
             patch("bot.extract_rating_from_chat", return_value=5), \
             patch("bot.get_system_message", new_callable=AsyncMock, return_value="Hi!"), \
             patch("bot.update_menu_language", new_callable=AsyncMock):

            await on_start(mock_update, mock_context)

        mock_rating.assert_called_once_with(mock_update.effective_user.id, 5)

    @pytest.mark.asyncio
    async def test_updates_menu_language(self, mock_update, mock_context):
        """Устанавливает меню команд на языке пользователя."""
        with patch("bot.upsert_user", new_callable=AsyncMock), \
             patch("bot.update_tg_rating", new_callable=AsyncMock), \
             patch("bot.extract_rating_from_chat", return_value=None), \
             patch("bot.get_system_message", new_callable=AsyncMock, return_value="Hi!"), \
             patch("bot.update_menu_language", new_callable=AsyncMock) as mock_menu:

            await on_start(mock_update, mock_context)

        mock_menu.assert_called_once_with(
            mock_context.bot, mock_update.effective_user.language_code
        )


class TestOnText:
    """Тесты для on_text()."""

    @pytest.mark.asyncio
    async def test_empty_text_returns_early(self, mock_update, mock_context):
        """Пустой текст → ранний return."""
        mock_update.message.text = "   "

        with patch("bot.update_last_msg_at", new_callable=AsyncMock) as mock_update_msg:
            await on_text(mock_update, mock_context)

        mock_update_msg.assert_not_called()

    @pytest.mark.asyncio
    async def test_generates_and_sends_response(self, mock_update, mock_context):
        """Генерирует ответ и отправляет."""
        mock_update.message.text = "Привет!"

        with patch("bot.update_last_msg_at", new_callable=AsyncMock), \
             patch("bot.generate_response", new_callable=AsyncMock, return_value="Ответ"):

            await on_text(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_with("Ответ")

    @pytest.mark.asyncio
    async def test_error_sends_error_message(self, mock_update, mock_context):
        """Ошибка генерации → отправляет error message."""
        mock_update.message.text = "Test"

        with patch("bot.update_last_msg_at", new_callable=AsyncMock), \
             patch("bot.generate_response", new_callable=AsyncMock, side_effect=Exception("API fail")), \
             patch("bot.get_system_message", new_callable=AsyncMock, return_value="Ошибка"):

            await on_text(mock_update, mock_context)

        mock_update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_updates_last_msg_at(self, mock_update, mock_context):
        """Обновляет last_msg_at."""
        mock_update.message.text = "Hello"

        with patch("bot.update_last_msg_at", new_callable=AsyncMock) as mock_update_msg, \
             patch("bot.generate_response", new_callable=AsyncMock, return_value="Reply"):

            await on_text(mock_update, mock_context)

        mock_update_msg.assert_called_once_with(mock_update.effective_user.id)


class TestOnError:
    """Тесты для on_error()."""

    @pytest.mark.asyncio
    async def test_does_not_crash(self, mock_context):
        """Обработчик ошибок не падает."""
        mock_context.error = Exception("Test error")

        # Не должно бросить исключение
        await on_error(MagicMock(), mock_context)
