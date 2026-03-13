# bot.py — Telegram-бот TalkGuru (обработчики событий и запуск)

import os
import traceback

# Отключаем буферизацию
os.environ["PYTHONUNBUFFERED"] = "1"

import logging

# Отключаем лишние логи от библиотек ДО импорта telegram
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("telegram").setLevel(logging.ERROR)

from telegram import BotCommand, Update  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application, MessageHandler, CommandHandler,
    ConversationHandler, ContextTypes, filters,
)

from config import BOT_TOKEN, DEBUG_PRINT, PYROGRAM_API_ID, PYROGRAM_API_HASH  # noqa: E402
from utils.utils import get_timestamp  # noqa: E402
from clients.x402gate.openrouter import generate_response, generate_reply  # noqa: E402
from clients import pyrogram_client  # noqa: E402
from database.users import upsert_user, update_last_msg_at, update_tg_rating, save_session, clear_session  # noqa: E402
from utils.telegram_rating import extract_rating_from_chat  # noqa: E402
from system_messages import get_system_message, SYSTEM_MESSAGES  # noqa: E402


# ====== СОСТОЯНИЯ CONVERSATION ======
CONNECT_PHONE, CONNECT_CODE, CONNECT_2FA = range(3)


# ====== ОБРАБОТЧИКИ СОБЫТИЙ ======

async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    u = update.effective_user

    if DEBUG_PRINT:
        print(f"{get_timestamp()} [BOT] /start from user {u.id} (@{u.username})")

    # Сохраняем пользователя в БД
    await upsert_user(
        user_id=u.id,
        username=u.username,
        first_name=u.first_name,
        last_name=u.last_name,
        is_bot=u.is_bot,
        is_premium=bool(u.is_premium),
        language_code=u.language_code,
    )

    # Обновляем tg_rating (Telegram Stars) через getChat
    try:
        chat_obj = await context.bot.get_chat(u.id)
        rating = extract_rating_from_chat(chat_obj)
        await update_tg_rating(u.id, rating)
    except Exception as e:
        print(f"{get_timestamp()} [BOT] WARNING: Failed to get tg_rating for user {u.id}: {e}")

    # Приветствие на языке пользователя
    greeting = await get_system_message(u.language_code, "greeting")
    await update.message.reply_text(greeting)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений — генерирует ответ через ИИ."""
    u = update.effective_user
    c = update.effective_chat
    m = update.message

    message_text = m.text or ""
    if not message_text.strip():
        return

    if DEBUG_PRINT:
        try:
            print(f"{get_timestamp()} [BOT] Text from user {u.id}: '{message_text[:100]}'")
        except UnicodeEncodeError:
            print(f"{get_timestamp()} [BOT] Text from user {u.id}: [unicode text]")

    # Обновляем last_msg_at
    await update_last_msg_at(u.id)

    # Индикатор набора текста
    await context.bot.send_chat_action(chat_id=c.id, action="typing")

    try:
        # Генерируем ответ через OpenRouter (Gemini 3.1 Flash)
        response_text = await generate_response(message_text)

        # Отправляем ответ
        await m.reply_text(response_text)

        if DEBUG_PRINT:
            print(f"{get_timestamp()} [BOT] Response sent to user {u.id}")

    except Exception as e:
        print(f"{get_timestamp()} [BOT] ERROR generating response for user {u.id}: {e}")
        traceback.print_exc()
        error_msg = await get_system_message(u.language_code, "error")
        await m.reply_text(error_msg or SYSTEM_MESSAGES["error"])


# ====== ОБРАБОТЧИК ОШИБОК ======

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный обработчик ошибок."""
    print(f"{get_timestamp()} [BOT] ERROR: {context.error}")
    traceback.print_exc()


# ====== PYROGRAM: /connect ======

async def on_connect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /connect — начинает подключение аккаунта."""
    u = update.effective_user

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

    try:
        from pyrogram import Client

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


# ====== PYROGRAM: /disconnect ======

async def on_disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /disconnect — отключает аккаунт."""
    u = update.effective_user

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


# ====== ВОССТАНОВЛЕНИЕ СЕССИЙ ======

async def restore_sessions(app: Application) -> None:
    """Восстанавливает активные Pyrogram-сессии при старте бота."""
    from database import supabase

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


# ====== ЗАПУСК ======

def main() -> None:
    """Точка входа — запуск бота в polling-режиме."""
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не задан! Установите его в .env")
        return

    print(f"{get_timestamp()} [BOT] Starting TalkGuru bot...")

    # Устанавливаем callback для Pyrogram
    pyrogram_client.set_message_callback(on_pyrogram_message)

    # Создаём приложение
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ConversationHandler для /connect
    connect_handler = ConversationHandler(
        entry_points=[CommandHandler("connect", on_connect)],
        states={
            CONNECT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_connect_phone)],
            CONNECT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_connect_code)],
            CONNECT_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_connect_2fa)],
        },
        fallbacks=[CommandHandler("cancel", on_connect_cancel)],
    )

    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(connect_handler)
    app.add_handler(CommandHandler("disconnect", on_disconnect))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # Глобальный обработчик ошибок
    app.add_error_handler(on_error)

    print(f"{get_timestamp()} [BOT] Bot is running (polling mode)...")

    # Запуск polling
    app.run_polling(drop_pending_updates=True)


async def post_init(app: Application) -> None:
    """Выполняется после инициализации приложения."""
    # Меню команд
    await app.bot.set_my_commands([
        BotCommand("start", "Начать"),
        BotCommand("connect", "Подключить аккаунт"),
        BotCommand("disconnect", "Отключить аккаунт"),
    ])

    # Восстанавливаем Pyrogram-сессии
    await restore_sessions(app)


if __name__ == "__main__":
    main()
