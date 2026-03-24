# tests/test_dashboard.py — Тесты для модуля dashboard

import time

from dashboard import stats


class TestDashboardStats:
    """Тесты для dashboard/stats.py."""

    def setup_method(self) -> None:
        """Сбрасывает синглтон статистики перед каждым тестом."""
        stats._stats = stats._GlobalStats()

    def test_record_llm_request(self) -> None:
        """Записывает LLM-запрос: счётчики, токены, модель."""
        stats.record_llm_request(
            model="gemini-2.5-pro",
            latency_s=1.5,
            tokens_in=100,
            tokens_out=50,
            reasoning_tokens=10,
        )

        assert stats._stats.llm_requests == 1
        assert stats._stats.total_tokens_in == 100
        assert stats._stats.total_tokens_out == 50
        assert stats._stats.total_reasoning_tokens == 10
        assert stats._stats.total_latency_s == 1.5
        assert stats._stats.models == {"gemini-2.5-pro": 1}

    def test_record_multiple_llm_requests(self) -> None:
        """Несколько запросов суммируются."""
        stats.record_llm_request("model-a", 1.0, 100, 50)
        stats.record_llm_request("model-b", 2.0, 200, 100)
        stats.record_llm_request("model-a", 0.5, 50, 25)

        assert stats._stats.llm_requests == 3
        assert stats._stats.total_tokens_in == 350
        assert stats._stats.total_tokens_out == 175
        assert stats._stats.total_latency_s == 3.5
        assert stats._stats.models == {"model-a": 2, "model-b": 1}

    def test_record_llm_error(self) -> None:
        """Счётчик ошибок LLM."""
        stats.record_llm_error()
        stats.record_llm_error()

        assert stats._stats.llm_errors == 2

    def test_record_draft(self) -> None:
        """Счётчик черновиков."""
        stats.record_draft()
        assert stats._stats.drafts_generated == 1

    def test_record_auto_reply(self) -> None:
        """Счётчик автоответов."""
        stats.record_auto_reply()
        stats.record_auto_reply()
        assert stats._stats.auto_replies_sent == 2

    def test_record_voice_transcription(self) -> None:
        """Счётчик голосовых транскрипций."""
        stats.record_voice_transcription()
        assert stats._stats.voice_transcriptions == 1

    def test_record_command(self) -> None:
        """Счётчик команд."""
        stats.record_command("/start")
        stats.record_command("/settings")
        stats.record_command("/start")

        assert stats._stats.commands == {"/start": 2, "/settings": 1}

    def test_update_balance(self) -> None:
        """Обновление баланса: initial и last."""
        stats.update_balance(10.0)
        assert stats._stats.initial_balance == 10.0
        assert stats._stats.last_balance == 10.0

        stats.update_balance(8.5)
        assert stats._stats.initial_balance == 10.0  # не меняется
        assert stats._stats.last_balance == 8.5

    def test_update_user_counts(self) -> None:
        """Обновление счётчиков пользователей."""
        stats.update_user_counts(total=100, connected=30, active_24h=15)

        assert stats._stats.total_users == 100
        assert stats._stats.connected_users == 30
        assert stats._stats.active_users_24h == 15

    def test_capture_log_info(self) -> None:
        """Лог INFO записывается корректно."""
        stats.capture_log("2026-03-20 12:00:00 UTC [BOT] Started")

        assert len(stats._stats.logs) == 1
        entry = stats._stats.logs[0]
        assert entry["level"] == "INFO"
        assert "[BOT] Started" in entry["message"]

    def test_capture_log_error(self) -> None:
        """Лог ERROR увеличивает счётчик ошибок."""
        stats.capture_log("2026-03-20 12:00:00 UTC [BOT] ERROR: connection failed")

        assert stats._stats.errors == 1
        assert stats._stats.logs[0]["level"] == "ERROR"

    def test_capture_log_warning(self) -> None:
        """Лог WARNING увеличивает счётчик предупреждений."""
        stats.capture_log("2026-03-20 12:00:00 UTC [X402GATE] WARNING: low balance")

        assert stats._stats.warnings == 1
        assert stats._stats.logs[0]["level"] == "WARNING"

    def test_capture_log_rolling_buffer(self) -> None:
        """Rolling buffer ограничен MAX_LOG_ENTRIES."""
        for i in range(stats.MAX_LOG_ENTRIES + 100):
            stats.capture_log(f"Line {i}")

        assert len(stats._stats.logs) == stats.MAX_LOG_ENTRIES

    def test_get_stats_snapshot(self) -> None:
        """get_stats() возвращает полный снапшот."""
        stats.record_llm_request("gpt-4", 2.0, 100, 50)
        stats.update_balance(5.0)

        snapshot = stats.get_stats()

        assert snapshot["llm_requests"] == 1
        assert snapshot["avg_latency_s"] == 2.0
        assert snapshot["last_balance"] == 5.0
        assert snapshot["models"] == {"gpt-4": 1}
        assert "uptime_s" in snapshot
        assert "errors" in snapshot

    def test_get_stats_balance_spent(self) -> None:
        """balance_spent = initial + topup_total - last."""
        stats.update_balance(10.0)
        stats.update_balance(7.5)

        snapshot = stats.get_stats()
        assert snapshot["balance_spent"] == 2.5

    def test_record_topup(self) -> None:
        """record_topup записывает точную сумму пополнения."""
        stats.record_topup(0.5)
        stats.record_topup(0.5)
        stats.record_topup(0.5)

        assert stats._stats.topup_count == 3
        assert stats._stats.topup_total == 1.5

    def test_update_balance_ignores_increase(self) -> None:
        """update_balance не считает рост баланса как topup — это делает record_topup."""
        stats.update_balance(1.0)
        stats.update_balance(5.0)  # баланс вырос, но topup не записан

        assert stats._stats.topup_count == 0
        assert stats._stats.topup_total == 0.0

    def test_get_stats_no_balance(self) -> None:
        """balance_spent = None если баланс не обновлялся."""
        snapshot = stats.get_stats()
        assert snapshot["balance_spent"] is None

    def test_get_logs_newest_first(self) -> None:
        """get_logs() возвращает записи от новых к старым."""
        stats.capture_log("First")
        time.sleep(0.01)
        stats.capture_log("Second")

        logs = stats.get_logs()
        assert logs[0]["message"] == "Second"
        assert logs[1]["message"] == "First"

    def test_get_logs_limit(self) -> None:
        """get_logs(limit=N) возвращает не больше N записей."""
        for i in range(10):
            stats.capture_log(f"Line {i}")

        logs = stats.get_logs(limit=3)
        assert len(logs) == 3

    def test_avg_latency_zero_requests(self) -> None:
        """Средняя латенция = 0 при 0 запросах."""
        snapshot = stats.get_stats()
        assert snapshot["avg_latency_s"] == 0


class TestDashboardAuth:
    """Тесты для dashboard/auth.py."""

    def test_check_auth_no_key_configured(self) -> None:
        """Без DASHBOARD_KEY — всегда False."""
        from unittest.mock import MagicMock, patch

        with patch("dashboard.auth.DASHBOARD_KEY", ""):
            from dashboard.auth import check_auth

            request = MagicMock()
            request.query = {}
            request.cookies = {}
            assert check_auth(request) is False

    def test_check_auth_correct_key_param(self) -> None:
        """Правильный ?key= → True."""
        from unittest.mock import MagicMock, patch

        with patch("dashboard.auth.DASHBOARD_KEY", "secret123"):
            from dashboard.auth import check_auth

            request = MagicMock()
            request.query = {"key": "secret123"}
            request.cookies = {}
            assert check_auth(request) is True

    def test_check_auth_wrong_key_param(self) -> None:
        """Неправильный ?key= → False."""
        from unittest.mock import MagicMock, patch

        with patch("dashboard.auth.DASHBOARD_KEY", "secret123"):
            from dashboard.auth import check_auth

            request = MagicMock()
            request.query = {"key": "wrong"}
            request.cookies = {}
            assert check_auth(request) is False

    def test_check_auth_correct_cookie(self) -> None:
        """Правильный cookie → True."""
        from unittest.mock import MagicMock, patch

        with patch("dashboard.auth.DASHBOARD_KEY", "secret123"):
            from dashboard.auth import check_auth

            request = MagicMock()
            request.query = {}
            request.cookies = {"dashboard_key": "secret123"}
            assert check_auth(request) is True
