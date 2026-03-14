# tests/test_telegram_rating.py — Тесты для utils/telegram_rating.py

from unittest.mock import MagicMock

from utils.telegram_rating import extract_rating_from_chat


class TestExtractRatingFromChat:
    """Тесты для extract_rating_from_chat()."""

    def test_none_chat_returns_none(self):
        assert extract_rating_from_chat(None) is None

    def test_rating_from_api_kwargs(self):
        """Рейтинг в api_kwargs → возвращает число."""
        chat = MagicMock()
        chat.api_kwargs = {"rating": {"rating": 5}}
        # Убираем атрибут rating напрямую, чтобы до него не дошло
        del chat.rating
        result = extract_rating_from_chat(chat)
        assert result == 5

    def test_rating_from_to_dict(self):
        """Рейтинг в to_dict() → возвращает число."""
        chat = MagicMock()
        chat.api_kwargs = {}  # Пусто
        chat.to_dict.return_value = {"rating": {"rating": 3}}
        del chat.rating
        result = extract_rating_from_chat(chat)
        assert result == 3

    def test_rating_from_attribute(self):
        """Рейтинг как атрибут объекта chat.rating.rating."""
        chat = MagicMock()
        chat.api_kwargs = {}
        chat.to_dict.return_value = {}
        rating_obj = MagicMock()
        rating_obj.rating = 7
        chat.rating = rating_obj
        result = extract_rating_from_chat(chat)
        assert result == 7

    def test_no_rating_returns_none(self):
        """Нет рейтинга нигде → None."""
        chat = MagicMock()
        chat.api_kwargs = {}
        chat.to_dict.return_value = {}
        del chat.rating
        result = extract_rating_from_chat(chat)
        assert result is None

    def test_negative_rating_returns_none(self):
        """Отрицательный рейтинг → None."""
        chat = MagicMock()
        chat.api_kwargs = {"rating": {"rating": -1}}
        del chat.rating
        result = extract_rating_from_chat(chat)
        assert result is None

    def test_zero_rating_returns_zero(self):
        """Нулевой рейтинг → 0 (валидное значение)."""
        chat = MagicMock()
        chat.api_kwargs = {"rating": {"rating": 0}}
        del chat.rating
        result = extract_rating_from_chat(chat)
        assert result == 0

    def test_non_dict_rating_in_api_kwargs(self):
        """Если rating в api_kwargs не dict → пропускает."""
        chat = MagicMock()
        chat.api_kwargs = {"rating": 42}  # Не dict
        chat.to_dict.return_value = {}
        del chat.rating
        result = extract_rating_from_chat(chat)
        assert result is None
