# logic/moderation.py — Пост-модерация сгенерированных ответов ИИ

from config import MODERATION_MODEL, MODEL_REASONING_EFFORT
from prompts import MODERATION_PROMPT
from clients.x402gate.openrouter import generate_response
from utils.utils import get_timestamp

async def check_if_refusal(text: str) -> bool:
    """
    Проверяет, является ли текст от модели отказом отвечать из-за цензуры.
    Возвращает True, если это отказ, и False в противном случае.
    """
    if not text or not text.strip():
        return False
        
    try:
        response = await generate_response(
            user_message=text,
            model=MODERATION_MODEL,
            system_prompt=MODERATION_PROMPT,
            reasoning_effort=MODEL_REASONING_EFFORT.get(MODERATION_MODEL, "low")
        )
        
        result = response.strip().upper()
        is_refusal = "YES" in result
        
        if is_refusal:
            print(f"{get_timestamp()} [WARNING] [MODERATION] Blocked refusal response: {text[:50]}...")
            
        return is_refusal
    except Exception as e:
        print(f"{get_timestamp()} [MODERATION] Error during moderation check: {e}")
        # Если проверка упала, пропускаем текст, чтобы не сломать основной флоу
        return False
