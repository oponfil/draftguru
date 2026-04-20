# clients/vision_client.py — Модуль для анализа фото через Vision LLM

import base64

from clients.x402gate.openrouter import generate_response
from config import PHOTO_ANALYSIS_MODEL, DEBUG_PRINT
from prompts import VISION_PROMPT
from utils.utils import get_timestamp


async def analyze_photo_bytes(image_bytes: bytes) -> str | None:
    """Анализирует фото через Vision-модель и возвращает текстовое описание.
    
    Args:
        image_bytes: Сырые байты изображения (JPEG, PNG).
        
    Returns:
        Текстовое описание содержимого или None при ошибке.
    """
    try:
        base64_img = base64.b64encode(image_bytes).decode("utf-8")
        
        user_message_content = [
            {"type": "text", "text": "What is in this image?"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
        ]
        
        # Запрос к OpenRouter.
        # record_llm_request уже вызывается внутри generate_response
        res = await generate_response(
            user_message=user_message_content,
            model=PHOTO_ANALYSIS_MODEL,
            system_prompt=VISION_PROMPT,
            reasoning_effort="low",  # Для vision-задач обычно достаточно low/none
            chat_history=None
        )
        if DEBUG_PRINT:
            print(f"{get_timestamp()} [VISION] Photo analyzed successfully ({len(res)} chars)")
        return res
    except Exception as e:
        print(f"{get_timestamp()} [VISION] ERROR analyzing photo: {e}")
        return None
