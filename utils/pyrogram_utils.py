# utils/pyrogram_utils.py — Утилиты для Pyrogram Client API

from telegram.ext import Application

from utils.utils import get_timestamp
from clients import pyrogram_client
from database import supabase


async def restore_sessions(app: Application) -> None:
    """Восстанавливает активные Pyrogram-сессии при старте бота."""
    try:
        result = supabase.table("users").select(
            "user_id, session_string"
        ).not_.is_("session_string", "null").execute()

        if not result.data:
            return

        count = 0
        for row in result.data:
            user_id = row["user_id"]
            session_string = row["session_string"]
            if session_string:
                ok = await pyrogram_client.start_listening(user_id, session_string)
                if ok:
                    count += 1

        if count > 0:
            print(f"{get_timestamp()} [BOT] Restored {count} Pyrogram session(s)")

    except Exception as e:
        print(f"{get_timestamp()} [BOT] ERROR restoring sessions: {e}")
