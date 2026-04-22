# logic/reply.py — Бизнес-логика генерации ответов

from clients.x402gate.openrouter import generate_response
from config import FREE_LLM_MODEL, MODEL_REASONING_EFFORT
from prompts import build_reply_prompt
from utils.utils import format_chat_history, get_local_time_string


async def generate_reply(
    chat_history: list[dict],
    user_info: dict | None = None,
    opponent_info: dict | None = None,
    model: str | None = None,
    custom_prompt: str = "",
    style: str | None = None,
    tz_offset: float = 0,
) -> str:
    """Генерирует ответ на основе контекста переписки.

    Args:
        chat_history: Список сообщений [{role, text, date?, name?}]
        user_info: Полная информация о пользователе (из БД)
        opponent_info: Информация об оппоненте (из Pyrogram)
        model: Модель OpenRouter (None — используется FREE_LLM_MODEL по умолчанию)
        custom_prompt: Пользовательский промпт из настроек
        style: Стиль общения (None = под пользователя)
        tz_offset: Смещение часового пояса пользователя (часы)

    Returns:
        Текст ответа от лица пользователя
    """
    history_text = format_chat_history(chat_history, user_info, opponent_info, tz_offset=tz_offset)

    effective_model = model or FREE_LLM_MODEL
    kwargs: dict = {
        "user_message": history_text,
        "system_prompt": build_reply_prompt(
            custom_prompt=custom_prompt, 
            style=style,
            local_time_str=get_local_time_string(tz_offset),
        ),
        "reasoning_effort": MODEL_REASONING_EFFORT.get(effective_model, "medium"),
    }
    if model:
        kwargs["model"] = model
    return await generate_response(**kwargs)
