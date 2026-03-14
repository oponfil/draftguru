# tests/test_utils.py — Тесты для utils/utils.py

import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.utils import get_timestamp, typing_action


class TestGetTimestamp:
    """Тесты для get_timestamp()."""

    def test_returns_string(self):
        result = get_timestamp()
        assert isinstance(result, str)

    def test_format_matches_utc(self):
        result = get_timestamp()
        # Формат: "2026-03-14 12:00:00 UTC"
        pattern = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$"
        assert re.match(pattern, result), f"Unexpected format: {result}"

    def test_ends_with_utc(self):
        result = get_timestamp()
        assert result.endswith("UTC")


class TestTypingAction:
    """Тесты для декоратора typing_action()."""

    @pytest.mark.asyncio
    async def test_sends_typing_action(self):
        """Декоратор вызывает send_chat_action('typing') перед обработчиком."""
        mock_handler = AsyncMock(return_value=None)
        decorated = typing_action(mock_handler)

        update = MagicMock()
        update.effective_chat.id = 12345
        context = MagicMock()
        context.bot.send_chat_action = AsyncMock()

        await decorated(update, context)

        context.bot.send_chat_action.assert_called_once_with(
            chat_id=12345, action="typing"
        )
        mock_handler.assert_called_once_with(update, context)

    @pytest.mark.asyncio
    async def test_preserves_return_value(self):
        """Декоратор пробрасывает возвращаемое значение обработчика."""
        mock_handler = AsyncMock(return_value=42)
        decorated = typing_action(mock_handler)

        update = MagicMock()
        update.effective_chat.id = 1
        context = MagicMock()
        context.bot.send_chat_action = AsyncMock()

        result = await decorated(update, context)
        assert result == 42

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        """Декоратор сохраняет имя оригинальной функции (functools.wraps)."""
        async def my_handler(update, context):
            pass

        decorated = typing_action(my_handler)
        assert decorated.__name__ == "my_handler"
