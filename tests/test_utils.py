# tests/test_utils.py — Тесты для utils/utils.py

import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.utils import (
    extract_autonomous_delay,
    format_chat_history,
    format_participants,
    format_profile,
    get_local_time_string,
    get_timestamp,
    typing_action,
)


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
        """Декоратор вызывает send_chat_action('typing') хотя бы раз."""
        mock_handler = AsyncMock(return_value=None)
        decorated = typing_action(mock_handler)

        update = MagicMock()
        update.effective_chat.id = 12345
        context = MagicMock()
        context.bot.send_chat_action = AsyncMock()

        await decorated(update, context)

        context.bot.send_chat_action.assert_called_with(
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


class TestFormatProfile:
    """Тесты для format_profile()."""

    def test_none_info_returns_label(self):
        """Без данных возвращает label."""
        assert format_profile(None, "You") == "You"

    def test_empty_dict_returns_label(self):
        """Пустой словарь возвращает label."""
        assert format_profile({}, "Them") == "Them"

    def test_first_name_only(self):
        """Только имя."""
        assert format_profile({"first_name": "Алексей"}, "You") == "Алексей"

    def test_full_name(self):
        """Имя и фамилия."""
        info = {"first_name": "Алексей", "last_name": "Иванов"}
        assert format_profile(info, "You") == "Алексей Иванов"

    def test_with_username(self):
        """Username игнорируется — возвращается только имя."""
        info = {"first_name": "Алексей", "username": "alexey"}
        assert format_profile(info, "You") == "Алексей"

    def test_full_profile(self):
        """Имя + фамилия, username игнорируется."""
        info = {"first_name": "Алексей", "last_name": "Иванов", "username": "alexey"}
        assert format_profile(info, "You") == "Алексей Иванов"

    def test_username_only(self):
        """Только username без имени — возвращает label."""
        info = {"username": "alexey"}
        assert format_profile(info, "You") == "You"


class TestFormatChatHistory:
    """Тесты для format_chat_history()."""

    def test_empty_history(self):
        """Пустая история — только заголовок."""
        result = format_chat_history([], None, None)
        assert "PARTICIPANTS:" in result
        assert "You: You" in result
        assert "Them: Them" in result

    def test_with_names(self):
        """Имена отображаются в заголовке и сообщениях."""
        history = [{"role": "user", "text": "Привет"}, {"role": "other", "text": "Хай", "name": "Марина"}]
        user_info = {"first_name": "Алексей"}
        opponent_info = {"first_name": "Марина"}

        result = format_chat_history(history, user_info, opponent_info)
        assert "PARTICIPANTS:" in result
        assert "CHAT HISTORY:" in result
        assert "Алексей: Привет" in result
        assert "Марина: Хай" in result
        assert "You: Алексей" in result
        assert "Them: Марина" in result

    def test_with_timestamps(self):
        """Даты форматируются как [YYYY-MM-DD HH:MM]."""
        dt = datetime(2026, 3, 14, 14, 30, tzinfo=timezone.utc)
        history = [{"role": "user", "text": "Тест", "date": dt}]

        result = format_chat_history(history)
        assert "[2026-03-14 14:30]" in result

    def test_without_timestamps(self):
        """Сообщения без даты форматируются без скобок."""
        history = [{"role": "user", "text": "Тест"}]

        result = format_chat_history(history)
        assert "You: Тест" in result
        assert "[" not in result.split("\n")[-1]

    def test_mixed_timestamps(self):
        """Смешанная история — с датой и без."""
        dt = datetime(2026, 3, 14, 14, 30, tzinfo=timezone.utc)
        history = [
            {"role": "user", "text": "С датой", "date": dt},
            {"role": "other", "text": "Без даты", "name": "Them"},
        ]

        result = format_chat_history(history)
        assert "[2026-03-14 14:30]" in result
        assert "Them: Без даты" in result

    def test_tz_offset_positive(self):
        """tz_offset=7 сдвигает время на +7 часов."""
        dt = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
        history = [{"role": "user", "text": "Тест", "date": dt}]

        result = format_chat_history(history, tz_offset=7)
        assert "[2026-03-14 17:00]" in result

    def test_tz_offset_negative(self):
        """tz_offset=-5 сдвигает время на -5 часов."""
        dt = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
        history = [{"role": "user", "text": "Тест", "date": dt}]

        result = format_chat_history(history, tz_offset=-5)
        assert "[2026-03-14 05:00]" in result

    def test_tz_offset_half_hour(self):
        """tz_offset=5.5 сдвигает время на +5:30."""
        dt = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
        history = [{"role": "user", "text": "Тест", "date": dt}]

        result = format_chat_history(history, tz_offset=5.5)
        assert "[2026-03-14 15:30]" in result

    def test_tz_offset_zero_unchanged(self):
        """tz_offset=0 — поведение не меняется."""
        dt = datetime(2026, 3, 14, 14, 30, tzinfo=timezone.utc)
        history = [{"role": "user", "text": "Тест", "date": dt}]

        result = format_chat_history(history, tz_offset=0)
        assert "[2026-03-14 14:30]" in result

    def test_bio_shown_in_participants(self):
        """Bio оппонента отображается в PARTICIPANTS блоке."""
        history = [{"role": "other", "text": "Привет", "name": "Марина"}]
        opponent_info = {"first_name": "Марина", "bio": "Дизайнер из Москвы"}

        result = format_chat_history(history, None, opponent_info)
        assert "Them bio: Дизайнер из Москвы" in result

    def test_bio_absent_when_none(self):
        """Строка bio отсутствует когда bio = None."""
        history = [{"role": "other", "text": "Привет", "name": "Марина"}]
        opponent_info = {"first_name": "Марина", "bio": None}

        result = format_chat_history(history, None, opponent_info)
        assert "bio" not in result

    def test_bio_absent_when_missing(self):
        """Строка bio отсутствует когда ключ bio отсутствует."""
        history = [{"role": "other", "text": "Привет", "name": "Марина"}]
        opponent_info = {"first_name": "Марина"}

        result = format_chat_history(history, None, opponent_info)
        assert "bio" not in result

    def test_you_bio_shown(self):
        """Bio владельца отображается в PARTICIPANTS блоке."""
        history = [{"role": "other", "text": "Привет", "name": "Марина"}]
        user_info = {"first_name": "Алексей", "bio": "Программист из РФ"}

        result = format_chat_history(history, user_info, None)
        assert "You bio: Программист из РФ" in result


class TestFormatParticipants:
    """Тесты для format_participants()."""

    def test_empty_inputs_produce_default_block(self):
        result = format_participants()
        assert result.startswith("PARTICIPANTS:")
        assert "You: You" in result
        assert "Them: Them" in result
        assert "bio" not in result

    def test_only_user_info(self):
        result = format_participants(user_info={"first_name": "Alex", "bio": "engineer"})
        assert "You: Alex" in result
        assert "You bio: engineer" in result
        assert "Them: Them" in result

    def test_only_opponent_info(self):
        result = format_participants(
            opponent_info={"first_name": "Maria", "username": "maria", "bio": "designer"},
        )
        assert "Them: Maria" in result
        assert "Them bio: designer" in result

    def test_extends_them_with_chat_history_speakers(self):
        """В групповых чатах список Them дополняется именами из истории."""
        history = [
            {"role": "user", "text": "hi"},
            {"role": "other", "text": "hello", "name": "Alice"},
            {"role": "other", "text": "yo", "name": "Bob", "last_name": "Smith"},
            {"role": "other", "text": "again", "name": "Alice"},  # дубликат игнорится
        ]
        result = format_participants(chat_history=history)
        assert "Them: Alice, Bob Smith" in result

    def test_opponent_first_then_history(self):
        history = [
            {"role": "other", "text": "hi", "name": "Bob"},
        ]
        result = format_participants(
            opponent_info={"first_name": "Alice", "username": "alice"},
            chat_history=history,
        )
        them_line = next(line for line in result.splitlines() if line.startswith("Them:"))
        assert "Alice" in them_line
        assert "Bob" in them_line
        assert them_line.index("Alice") < them_line.index("Bob")


class TestExtractAutonomousDelay:
    """Тесты для extract_autonomous_delay()."""

    def test_delay_seconds(self):
        """Корректный тег [DELAY: 120] → извлекается задержка."""
        text, delay, is_manual = extract_autonomous_delay("Привет! [DELAY: 120]")
        assert text == "Привет!"
        assert delay == 120
        assert is_manual is False

    def test_delay_manual(self):
        """Тег [DELAY: MANUAL] → is_manual=True."""
        text, delay, is_manual = extract_autonomous_delay("Не уверен [DELAY: MANUAL]")
        assert text == "Не уверен"
        assert delay is None
        assert is_manual is True

    def test_no_tag(self):
        """Текст без тега → возвращается как есть."""
        text, delay, is_manual = extract_autonomous_delay("Обычный текст")
        assert text == "Обычный текст"
        assert delay is None
        assert is_manual is False

    def test_empty_string(self):
        """Пустая строка → пустая строка."""
        text, delay, is_manual = extract_autonomous_delay("")
        assert text == ""
        assert delay is None
        assert is_manual is False

    def test_tag_not_at_end(self):
        """Тег в середине текста → извлекается (case-insensitive, любое место)."""
        text, delay, is_manual = extract_autonomous_delay("Начало [DELAY: 60] и продолжение")
        assert text == "Начало  и продолжение"
        assert delay == 60
        assert is_manual is False

    def test_delay_zero(self):
        """[DELAY: 0] → граничный случай, задержка 0 секунд."""
        text, delay, is_manual = extract_autonomous_delay("Мгновенно [DELAY: 0]")
        assert text == "Мгновенно"
        assert delay == 0
        assert is_manual is False

    def test_delay_large_value(self):
        """[DELAY: 28800] → 8 часов."""
        text, delay, is_manual = extract_autonomous_delay("Доброе утро [DELAY: 28800]")
        assert text == "Доброе утро"
        assert delay == 28800
        assert is_manual is False

    def test_trailing_whitespace(self):
        """Пробелы после тега → всё равно парсится."""
        text, delay, is_manual = extract_autonomous_delay("Текст [DELAY: 30]  ")
        assert text == "Текст"
        assert delay == 30

    def test_multiline_text(self):
        """Многострочный текст с тегом в конце."""
        text, delay, is_manual = extract_autonomous_delay("Строка 1\nСтрока 2 [DELAY: 15]")
        assert text == "Строка 1\nСтрока 2"
        assert delay == 15

    def test_suffix_s(self):
        """[DELAY: 15s] → суффикс 's' игнорируется, задержка 15."""
        text, delay, is_manual = extract_autonomous_delay("Текст [DELAY: 15s]")
        assert text == "Текст"
        assert delay == 15
        assert is_manual is False

    def test_suffix_sec(self):
        """[DELAY: 30 sec] → суффикс 'sec' игнорируется."""
        text, delay, is_manual = extract_autonomous_delay("Текст [DELAY: 30 sec]")
        assert text == "Текст"
        assert delay == 30

    def test_suffix_seconds(self):
        """[DELAY: 60 seconds] → суффикс 'seconds' игнорируется."""
        text, delay, is_manual = extract_autonomous_delay("Текст [DELAY: 60 seconds]")
        assert text == "Текст"
        assert delay == 60

    def test_suffix_case_insensitive(self):
        """[DELAY: 10S] → суффикс в верхнем регистре."""
        text, delay, is_manual = extract_autonomous_delay("Текст [DELAY: 10S]")
        assert text == "Текст"
        assert delay == 10

    def test_malformed_repetition(self):
        """[DELAY: 15ждууу 🖤 [DELAY: 15] → извлекает 15, удаляет сломанный тег и повторения."""
        text, delay, is_manual = extract_autonomous_delay("ждууу 🖤 [DELAY: 15ждууу 🖤 [DELAY: 15]")
        assert text == "ждууу 🖤"
        assert delay == 15
        assert is_manual is False

    def test_suffix_minutes_short(self):
        """[DELAY: 5m] → 5 минут, конвертируется в 300 секунд."""
        text, delay, is_manual = extract_autonomous_delay("Текст [DELAY: 5m]")
        assert text == "Текст"
        assert delay == 300
        assert is_manual is False

    def test_suffix_minutes_full(self):
        """[DELAY: 2 minutes] → 120 секунд."""
        text, delay, is_manual = extract_autonomous_delay("Текст [DELAY: 2 minutes]")
        assert text == "Текст"
        assert delay == 120

    def test_suffix_min(self):
        """[DELAY: 15 min] → 15 минут = 900 секунд."""
        text, delay, is_manual = extract_autonomous_delay("Текст [DELAY: 15 min]")
        assert text == "Текст"
        assert delay == 900


class TestGetLocalTimeString:
    """Тесты для get_local_time_string()."""

    def test_format_includes_weekday(self):
        """Формат содержит дату, время и название дня недели в скобках."""
        result = get_local_time_string(0)
        # Формат: "2026-03-14 12:00 (Saturday)"
        pattern = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} \([A-Za-z]+\)$"
        assert re.match(pattern, result), f"Unexpected format: {result}"

    def test_tz_offset_shifts_time(self):
        """tz_offset сдвигает время относительно UTC."""
        plus_3 = get_local_time_string(3)
        minus_3 = get_local_time_string(-3)
        assert plus_3 != minus_3
