# tests/test_database_init.py — Тесты retry-логики run_supabase

from unittest.mock import AsyncMock, patch

import pytest

from database import run_supabase


class TemporaryDbError(Exception):
    """Временная ошибка БД для тестов."""


class PermanentDbError(Exception):
    """Невременная ошибка БД для тестов."""


class TestRunSupabase:
    """Тесты для run_supabase()."""

    @pytest.mark.asyncio
    async def test_retries_temporary_error_and_succeeds(self):
        """Повторяет временную ошибку и возвращает результат при успехе."""
        operation = object()
        to_thread = AsyncMock(side_effect=[TemporaryDbError("service unavailable"), "ok"])

        with patch("database.asyncio.to_thread", to_thread), \
             patch("database.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await run_supabase(operation)

        assert result == "ok"
        assert to_thread.await_count == 2
        mock_sleep.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_after_retry_limit_for_temporary_error(self):
        """Пробрасывает временную ошибку после исчерпания retry."""
        operation = object()
        to_thread = AsyncMock(side_effect=TemporaryDbError("connection reset by peer"))

        with patch("database.asyncio.to_thread", to_thread), \
             patch("database.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(TemporaryDbError):
                await run_supabase(operation)

        assert to_thread.await_count == 3
        assert mock_sleep.await_count == 2

    @pytest.mark.asyncio
    async def test_does_not_retry_non_retriable_error(self):
        """Не повторяет логическую ошибку запроса."""
        operation = object()
        to_thread = AsyncMock(side_effect=PermanentDbError("column does not exist"))

        with patch("database.asyncio.to_thread", to_thread), \
             patch("database.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(PermanentDbError):
                await run_supabase(operation)

        assert to_thread.await_count == 1
        mock_sleep.assert_not_awaited()
