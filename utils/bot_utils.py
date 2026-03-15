# utils/bot_utils.py — Утилиты для Telegram Bot API

from telegram import BotCommand

from config import DEBUG_PRINT
from utils.utils import get_timestamp
from system_messages import get_system_messages


async def update_menu_language(bot, language_code: str | None) -> None:
    """Устанавливает меню команд на языке пользователя."""
    lang = (language_code or "en").lower()
    if lang == "en":
        return  # Английский уже установлен по умолчанию

    try:
        messages = await get_system_messages(lang)
        await bot.set_my_commands(
            [
                BotCommand("status", messages.get("menu_status", "Connection status")),
                BotCommand("connect", messages.get("menu_connect", "Connect account")),
                BotCommand("disconnect", messages.get("menu_disconnect", "Disconnect account")),
            ],
            language_code=lang,
        )
        if DEBUG_PRINT:
            print(f"{get_timestamp()} [BOT] Menu commands set for language: {lang}")
    except Exception as e:
        print(f"{get_timestamp()} [BOT] ERROR setting menu for {lang}: {e}")
