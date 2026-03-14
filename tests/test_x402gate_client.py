# tests/test_x402gate_client.py — Тесты для clients/x402gate/__init__.py

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clients.x402gate import X402GateClient, TopupError


class TestX402GateClientInit:
    """Тесты инициализации X402GateClient."""

    def test_available_with_key(self):
        """available=True если есть приватный ключ."""
        client = X402GateClient(private_key="0x" + "ab" * 32)
        assert client.available is True

    def test_not_available_without_key(self):
        """available=False без ключа."""
        with patch("clients.x402gate.EVM_PRIVATE_KEY", ""):
            client = X402GateClient(base_url="https://test.io", private_key="")
        assert client.available is False

    def test_normalizes_key_without_0x(self):
        """Добавляет 0x к ключу если его нет."""
        key = "ab" * 32
        client = X402GateClient(private_key=key)
        assert client.available is True


class TestPrepaidHeaders:
    """Тесты для _prepaid_headers()."""

    def test_headers_contain_required_keys(self):
        client = X402GateClient(private_key="0x" + "ab" * 32)
        headers = client._prepaid_headers("/v1/openrouter/chat/completions")

        assert "X-PREPAID-PUBKEY" in headers
        assert "X-PREPAID-SIGNATURE" in headers
        assert "X-PREPAID-TIMESTAMP" in headers

    def test_pubkey_is_eth_address(self):
        client = X402GateClient(private_key="0x" + "ab" * 32)
        headers = client._prepaid_headers("/v1/test")

        pubkey = headers["X-PREPAID-PUBKEY"]
        assert pubkey.startswith("0x")
        assert len(pubkey) == 42  # Ethereum address

    def test_timestamp_is_numeric(self):
        client = X402GateClient(private_key="0x" + "ab" * 32)
        headers = client._prepaid_headers("/v1/test")

        ts = headers["X-PREPAID-TIMESTAMP"]
        assert ts.isdigit()


class TestGetBalance:
    """Тесты для get_balance()."""

    @pytest.mark.asyncio
    async def test_parses_balance(self):
        client = X402GateClient(private_key="0x" + "ab" * 32)

        mock_response = MagicMock()
        mock_response.json.return_value = {"balance": 1.5}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockHTTP:
            mock_http = AsyncMock()
            MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockHTTP.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=mock_response)

            balance = await client.get_balance()

        assert balance == 1.5
        assert client._prepaid_balance == 1.5

    @pytest.mark.asyncio
    async def test_raises_without_key(self):
        with patch("clients.x402gate.EVM_PRIVATE_KEY", ""):
            client = X402GateClient(base_url="https://test.io", private_key="")
        with pytest.raises(ValueError, match="EVM_PRIVATE_KEY"):
            await client.get_balance()


class TestRequest:
    """Тесты для request()."""

    @pytest.mark.asyncio
    async def test_raises_when_not_available(self):
        with patch("clients.x402gate.EVM_PRIVATE_KEY", ""):
            client = X402GateClient(base_url="https://test.io", private_key="")
        with pytest.raises(ValueError, match="EVM_PRIVATE_KEY"):
            await client.request("/v1/test", {"data": "test"})

    @pytest.mark.asyncio
    async def test_successful_request(self):
        """Успешный запрос (200) обновляет баланс из header."""
        client = X402GateClient(private_key="0x" + "ab" * 32)
        client._prepaid_balance = 1.0  # Уже есть баланс

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"result": "ok"}}
        mock_response.headers = {"X-Prepaid-Balance": "0.85"}

        with patch("httpx.AsyncClient") as MockHTTP:
            mock_http = AsyncMock()
            MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockHTTP.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=mock_response)

            result = await client.request("/v1/test", {"msg": "hi"})

        assert result == {"data": {"result": "ok"}}
        assert client._prepaid_balance == 0.85

    @pytest.mark.asyncio
    async def test_non_200_raises(self):
        """Ответ не-200 → RuntimeError."""
        client = X402GateClient(private_key="0x" + "ab" * 32)
        client._prepaid_balance = 1.0

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient") as MockHTTP:
            mock_http = AsyncMock()
            MockHTTP.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockHTTP.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=mock_response)

            with pytest.raises(RuntimeError, match="500"):
                await client.request("/v1/test", {})


class TestTopupError:
    """Тесты для TopupError."""

    def test_is_runtime_error(self):
        err = TopupError("payment failed")
        assert isinstance(err, RuntimeError)
        assert str(err) == "payment failed"
