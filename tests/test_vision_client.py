import base64
from unittest.mock import AsyncMock, patch

import pytest

from clients.vision_client import analyze_photo_bytes


class TestAnalyzePhotoBytes:
    """Тесты для clients.vision_client.analyze_photo_bytes."""

    @pytest.mark.asyncio
    async def test_successful_analysis(self):
        fake_bytes = b"fake_image_data"
        expected_base64 = base64.b64encode(fake_bytes).decode("utf-8")
        
        with patch("clients.vision_client.generate_response", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = "Это фотография кота."
            
            result = await analyze_photo_bytes(fake_bytes)
            
            assert result == "Это фотография кота."
            mock_generate.assert_awaited_once()
            
            args, kwargs = mock_generate.call_args
            assert kwargs["model"] == "google/gemini-3.1-flash-lite-preview"
            assert kwargs["reasoning_effort"] == "low"
            
            # Проверяем формирование payload
            user_msg = kwargs["user_message"]
            assert len(user_msg) == 2
            assert user_msg[0] == {"type": "text", "text": "What is in this image?"}
            assert user_msg[1] == {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{expected_base64}"}}

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        fake_bytes = b"fake_image_data"
        
        with patch("clients.vision_client.generate_response", new_callable=AsyncMock) as mock_generate:
            mock_generate.side_effect = Exception("OpenRouter error")
            
            with patch("builtins.print") as mock_print:
                result = await analyze_photo_bytes(fake_bytes)
                
            assert result is None
            mock_print.assert_called_once()
