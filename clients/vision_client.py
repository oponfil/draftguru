# clients/vision_client.py — Модуль для анализа фото через Vision LLM

import base64

from clients.x402gate.openrouter import generate_response
from config import PHOTO_ANALYSIS_MODEL, DEBUG_PRINT
from prompts import PHOTO_VISION_PROMPT, VIDEO_VISION_PROMPT
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
            system_prompt=PHOTO_VISION_PROMPT,
            reasoning_effort="low",  # Для vision-задач обычно достаточно low/none
            chat_history=None
        )
        if DEBUG_PRINT:
            print(f"{get_timestamp()} [VISION] Photo analyzed successfully ({len(res)} chars)")
        return res
    except Exception as e:
        print(f"{get_timestamp()} [VISION] ERROR analyzing photo: {e}")
        return None

async def analyze_video_bytes(video_bytes: bytes, mime_type: str = "video/mp4") -> str | None:
    """Анализирует короткое видео через Vision-модель (OpenRouter via base64) и возвращает текстовое описание и транскрипцию речи.
    
    Args:
        video_bytes: Сырые байты видеофайла.
        mime_type: MIME-тип видео (по умолчанию video/mp4).
        
    Returns:
        Текстовое описание содержимого и речи или None при ошибке.
    """
    try:
        base64_vid = base64.b64encode(video_bytes).decode("utf-8")
        
        user_message_content = [
            {"type": "text", "text": "What is in this video? Provide a detailed visual description and transcribe any speech verbatim."},
            {"type": "video_url", "video_url": {"url": f"data:{mime_type};base64,{base64_vid}"}}
        ]
        
        res = await generate_response(
            user_message=user_message_content,
            model=PHOTO_ANALYSIS_MODEL,
            system_prompt=VIDEO_VISION_PROMPT,
            reasoning_effort="low",
            chat_history=None
        )
        if DEBUG_PRINT:
            print(f"{get_timestamp()} [VISION] Video analyzed successfully ({len(res)} chars)")
        return res
    except Exception as e:
        print(f"{get_timestamp()} [VISION] ERROR analyzing video: {e}")
        return None
