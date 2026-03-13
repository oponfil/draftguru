# handlers/pyrogram_handlers.py — Обработчики /connect, /disconnect, Pyrogram callback

from pyrogram import Client
from telegram import BotCommand, Update
from telegram.ext import (
    Application, ConversationHandler, ContextTypes,
)

from config import PYROGRAM_API_ID, PYROGRAM_API_HASH, DEBUG_PRINT
from utils.utils import get_timestamp
from clients.x402gate.openrouter import generate_reply
from clients import pyrogram_client
from database import supabase
from database.users import save_session, clear_session
from system_messages import get_system_message, get_system_messages


# ====== СОСТОЯНИЯ CONVERSATION ======
CONNECT_PHONE, CONNECT_CODE, CONNECT_2FA = range(3)


# ====== /connect ======

async def on_connect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /connect — начинает подключение аккаунта."""
    u = update.effective_user

    # Индикатор набора текста
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Проверяем, не подключён ли уже
    if pyrogram_client.is_active(u.id):
        msg = await get_system_message(u.language_code, "connect_already")
        await update.message.reply_text(msg)
        return ConversationHandler.END

    msg = await get_system_message(u.language_code, "connect_prompt_phone")
    await update.message.reply_text(msg)
    return CONNECT_PHONE


async def on_connect_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает номер телефона, отправляет код."""
    u = update.effective_user
    phone = update.message.text.strip()

    # Индикатор набора текста
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        client = Client(
            name=f"talkguru_{u.id}",
            api_id=PYROGRAM_API_ID,
            api_hash=PYROGRAM_API_HASH,
            phone_number=phone,
            in_memory=True,
        )
        await client.connect()
        sent_code = await client.send_code(phone)

        # Сохраняем в контекст для следующего шага
        context.user_data["pyrogram_client"] = client
        context.user_data["phone"] = phone
        context.user_data["phone_code_hash"] = sent_code.phone_code_hash

        msg = await get_system_message(u.language_code, "connect_prompt_code")
        await update.message.reply_text(msg)
        return CONNECT_CODE

    except Exception as e:
        print(f"{get_timestamp()} [BOT] ERROR connect phone for user {u.id}: {e}")
        msg = await get_system_message(u.language_code, "connect_error")
        await update.message.reply_text(msg)
        return ConversationHandler.END


async def on_connect_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает код подтверждения, авторизует пользователя."""
    u = update.effective_user
    code = update.message.text.strip()

    client = context.user_data.get("pyrogram_client")
    phone = context.user_data.get("phone")
    phone_code_hash = context.user_data.get("phone_code_hash")

    if not client or not phone:
        msg = await get_system_message(u.language_code, "connect_error")
        await update.message.reply_text(msg)
        return ConversationHandler.END

    try:
        await client.sign_in(phone, phone_code_hash, code)
    except Exception as e:
        error_name = type(e).__name__
        # Нужна 2FA
        if "password" in error_name.lower() or "two" in str(e).lower():
            msg = await get_system_message(u.language_code, "connect_prompt_2fa")
            await update.message.reply_text(msg)
            return CONNECT_2FA

        print(f"{get_timestamp()} [BOT] ERROR connect code for user {u.id}: {e}")
        await client.disconnect()
        msg = await get_system_message(u.language_code, "connect_error")
        await update.message.reply_text(msg)
        return ConversationHandler.END

    return await _finalize_connection(update, context, client)


async def on_connect_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает пароль 2FA."""
    u = update.effective_user
    password = update.message.text.strip()
    client = context.user_data.get("pyrogram_client")

    if not client:
        msg = await get_system_message(u.language_code, "connect_error")
        await update.message.reply_text(msg)
        return ConversationHandler.END

    try:
        await client.check_password(password)
    except Exception as e:
        print(f"{get_timestamp()} [BOT] ERROR connect 2FA for user {u.id}: {e}")
        await client.disconnect()
        msg = await get_system_message(u.language_code, "connect_error")
        await update.message.reply_text(msg)
        return ConversationHandler.END

    return await _finalize_connection(update, context, client)


async def _finalize_connection(update: Update, context: ContextTypes.DEFAULT_TYPE, client) -> int:
    """Завершает подключение: сохраняет сессию, запускает слушатель."""
    u = update.effective_user

    try:
        session_string = await client.export_session_string()
        await client.disconnect()

        # Сохраняем в БД
        await save_session(u.id, session_string)

        # Запускаем слушатель
        await pyrogram_client.start_listening(u.id, session_string)

        msg = await get_system_message(u.language_code, "connect_success")
        await update.message.reply_text(msg)
        print(f"{get_timestamp()} [BOT] User {u.id} connected via Pyrogram")

    except Exception as e:
        print(f"{get_timestamp()} [BOT] ERROR finalizing connection for user {u.id}: {e}")
        msg = await get_system_message(u.language_code, "connect_error")
        await update.message.reply_text(msg)

    # Очищаем контекст
    context.user_data.pop("pyrogram_client", None)
    context.user_data.pop("phone", None)
    context.user_data.pop("phone_code_hash", None)
    return ConversationHandler.END


async def on_connect_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена /connect."""
    context.user_data.pop("pyrogram_client", None)
    context.user_data.pop("phone", None)
    context.user_data.pop("phone_code_hash", None)
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


# ====== /disconnect ======

async def on_disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /disconnect — отключает аккаунт."""
    u = update.effective_user

    # Индикатор набора текста
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    if not pyrogram_client.is_active(u.id):
        msg = await get_system_message(u.language_code, "disconnect_not_connected")
        await update.message.reply_text(msg)
        return

    await pyrogram_client.stop_listening(u.id)
    await clear_session(u.id)

    msg = await get_system_message(u.language_code, "disconnect_success")
    await update.message.reply_text(msg)
    print(f"{get_timestamp()} [BOT] User {u.id} disconnected")


# ====== PYROGRAM CALLBACK ======

async def on_pyrogram_message(user_id: int, pyrogram_client_instance, message) -> None:
    """Вызывается при новом входящем сообщении в любом чате пользователя."""
    if not message.text:
        return

    chat_id = message.chat.id

    if DEBUG_PRINT:
        sender = message.from_user.first_name if message.from_user else "Unknown"
        print(f"{get_timestamp()} [PYROGRAM] New message for user {user_id} from {sender}: '{message.text[:50]}'")

    try:
        # Читаем историю чата
        history = await pyrogram_client.read_chat_history(user_id, chat_id)
        if not history:
            return

        # Генерируем ответ
        reply_text = await generate_reply(history)
        if not reply_text or not reply_text.strip():
            return

        # Устанавливаем черновик
        await pyrogram_client.set_draft(user_id, chat_id, reply_text.strip())

    except Exception as e:
        print(f"{get_timestamp()} [PYROGRAM] ERROR processing message for user {user_id}: {e}")


# ====== ВСПОМОГАТЕЛЬНЫЕ ======

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


async def update_menu_language(bot, language_code: str | None) -> None:
    """Устанавливает меню команд на языке пользователя."""
    lang = (language_code or "en").lower()
    if lang == "en":
        return  # Английский уже установлен по умолчанию

    try:
        messages = await get_system_messages(lang)
        await bot.set_my_commands(
            [
                BotCommand("start", messages.get("menu_start", "Start")),
                BotCommand("connect", messages.get("menu_connect", "Connect account")),
                BotCommand("disconnect", messages.get("menu_disconnect", "Disconnect account")),
            ],
            language_code=lang,
        )
        if DEBUG_PRINT:
            print(f"{get_timestamp()} [BOT] Menu commands set for language: {lang}")
    except Exception as e:
        print(f"{get_timestamp()} [BOT] ERROR setting menu for {lang}: {e}")
