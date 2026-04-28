# handlers/bot_handlers.py — Обработчики команд Telegram Bot API (/start, on_text)

import asyncio
import re
import traceback

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update, User
from telegram.ext import ContextTypes

from config import CHAT_PROMPT_MAX_LENGTH, USER_PROMPT_MAX_LENGTH, DEBUG_PRINT, FREE_LLM_MODEL, MODEL_REASONING_EFFORT, MAX_CONTEXT_MESSAGES, DEFAULT_LANGUAGE_CODE, CHAT_AUTONOMOUS_SENTINEL
from utils.utils import get_effective_model, get_timestamp, serialize_user_updates, typing_action, get_local_time_string, get_effective_auto_reply, extract_autonomous_delay, calculate_fallback_delay
from utils.bot_utils import update_user_menu
from utils.telegram_user import ensure_effective_user, upsert_effective_user
from clients.x402gate.openrouter import generate_response
from prompts import build_bot_chat_prompt, build_draft_prompt
from logic.rag import retrieve_context
from database.users import update_chat_prompt, update_last_msg_at, update_tg_rating, update_user_settings
from utils.telegram_rating import extract_rating_from_chat
from system_messages import get_system_message, SYSTEM_MESSAGES
from clients import pyrogram_client
from dashboard import stats as dash_stats
from handlers.connect_handler import on_connect
from handlers.pyrogram_handlers import register_bot_draft_and_schedule


@serialize_user_updates
@typing_action
async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    u = update.effective_user

    if DEBUG_PRINT:
        print(f"{get_timestamp()} [BOT] /start from user {u.id} (@{u.username})")
    dash_stats.record_command("/start")

    # Сохраняем пользователя в БД
    if not await upsert_effective_user(update):
        error_msg = await get_system_message(u.language_code, "error")
        await update.message.reply_text(error_msg or SYSTEM_MESSAGES["error"])
        return

    asyncio.create_task(update_last_msg_at(u.id))

    # Обновляем tg_rating (Telegram Stars) через getChat
    try:
        chat_obj = await context.bot.get_chat(u.id)
        rating = extract_rating_from_chat(chat_obj)
        await update_tg_rating(u.id, rating)
    except Exception as e:
        print(f"{get_timestamp()} [BOT] WARNING: Failed to get tg_rating for user {u.id}: {e}")

    # Приветствие на языке пользователя
    greeting = await get_system_message(u.language_code, "greeting")

    # Устанавливаем меню команд с учётом статуса подключения
    is_connected = pyrogram_client.is_active(u.id)

    if is_connected:
        await update.message.reply_text(greeting)
    else:
        connect_label = await get_system_message(u.language_code, "greeting_btn_connect")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(connect_label, callback_data="start:connect")]
        ])
        await update.message.reply_text(greeting, reply_markup=keyboard)

    await update_user_menu(context.bot, u.id, u.language_code, is_connected)


async def on_start_connect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback кнопки 'Connect' из приветственного сообщения.
    
    ВНИМАНИЕ: Без декоратора @serialize_user_updates!
    Функция только убирает кнопку и делегирует вызов в on_connect, который
    уже удерживает этот lock. Так как asyncio.Lock не reentrant, добавление
    декоратора сюда приведёт к вечной блокировке (deadlock) для пользователя.
    """
    query = update.callback_query
    await query.answer()

    # Убираем кнопку
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        if DEBUG_PRINT:
            print(f"{get_timestamp()} [BOT] Failed to remove reply markup: {e}")

    # Делегируем в on_connect
    await on_connect(update, context)


@typing_action
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений — генерирует ответ через ИИ."""
    u = update.effective_user
    m = update.message

    message_text = m.text or ""
    awaiting_prompt_input = (
        context.user_data.get("awaiting_prompt")
        or (context.user_data.get("awaiting_chat_prompt") is not None)
    )
    if not message_text.strip() and not awaiting_prompt_input:
        return

    await _process_text(update, context, u, m, message_text)


async def _handle_prompt_save(
    u: User, m: Message, context: ContextTypes.DEFAULT_TYPE, prompt_text: str, max_length: int,
    save_coro, msg_saved: str, msg_trunc: str, is_clearing: bool = False, msg_cleared: str | None = None
) -> None:
    """Вспомогательная функция для сохранения промпта и отправки уведомления."""
    was_truncated = len(prompt_text) > max_length
    if was_truncated:
        prompt_text = prompt_text[:max_length]

    saved = await save_coro
    if not saved:
        error_msg = await get_system_message(u.language_code, "error")
        await m.reply_text(error_msg)
        return

    context.user_data.pop("awaiting_chat_prompt", None)
    context.user_data.pop("awaiting_prompt", None)

    if is_clearing and msg_cleared:
        msg_key = msg_cleared
    else:
        msg_key = msg_trunc if was_truncated else msg_saved

    msg = await get_system_message(u.language_code, msg_key)
    if was_truncated:
        msg = msg.format(max_length=max_length)
    await m.reply_text(msg)
    if DEBUG_PRINT:
        print(f"{get_timestamp()} [BOT] Prompt saved for user {u.id}: {len(prompt_text)} chars")


async def _process_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    u: User, m: Message, message_text: str,
) -> None:
    """Внутренняя логика on_text, выполняется под per-user lock."""
    # Проверяем: пользователь вводит per-chat промпт?
    chat_prompt_chat_id = context.user_data.get("awaiting_chat_prompt")
    if chat_prompt_chat_id is not None:
        prompt_text = message_text.strip()
        is_clearing_prompt = prompt_text == ""
        
        save_coro = update_chat_prompt(
            u.id, chat_prompt_chat_id, None if is_clearing_prompt else prompt_text[:CHAT_PROMPT_MAX_LENGTH]
        )
        await _handle_prompt_save(
            u, m, context, prompt_text, CHAT_PROMPT_MAX_LENGTH, save_coro,
            msg_saved="settings_prompt_saved", msg_trunc="settings_prompt_truncated",
            is_clearing=is_clearing_prompt, msg_cleared="settings_prompt_cleared"
        )
        return

    # Проверяем: пользователь вводит кастомный промпт?
    if context.user_data.get("awaiting_prompt"):
        prompt_text = message_text.strip()
        save_coro = update_user_settings(u.id, {"custom_prompt": prompt_text[:USER_PROMPT_MAX_LENGTH]})
        await _handle_prompt_save(
            u, m, context, prompt_text, USER_PROMPT_MAX_LENGTH, save_coro,
            msg_saved="settings_prompt_saved", msg_trunc="settings_prompt_truncated",
        )
        return

    try:
        user = await ensure_effective_user(update)

        # Обновляем last_msg_at только после гарантированного наличия записи пользователя.
        asyncio.create_task(update_last_msg_at(u.id))

        # === Cold Outreach Generation via Username ===
        username_match = re.match(r"^(@[a-zA-Z0-9_]{5,32}|https?://t\.me/[a-zA-Z0-9_]{5,32}|t\.me/[a-zA-Z0-9_]{5,32})(?:\s+(.*))?$", message_text.strip(), flags=re.IGNORECASE)
        if username_match:
            raw_username = username_match.group(1)
            instruction = username_match.group(2) or ""
            
            if not pyrogram_client.is_active(u.id):
                error_msg = await get_system_message(u.language_code, "cold_outreach_not_connected")
                await m.reply_text(error_msg)
                return

            gen_msg_text = (await get_system_message(u.language_code, "cold_outreach_generating")).format(username=raw_username)
            status_msg = await m.reply_text(gen_msg_text)
            
            target_chat = await pyrogram_client.resolve_target_chat(u.id, raw_username)
            if not target_chat:
                error_msg = (await get_system_message(u.language_code, "cold_outreach_not_found")).format(username=raw_username)
                await status_msg.edit_text(error_msg)
                return
                
            chat_id = target_chat["chat_id"]
            
            user_settings = (user or {}).get("settings") or {}
            style = user_settings.get("style", "userlike")
            tz_offset = user_settings.get("tz_offset", 0) or 0
            
            auto_reply = get_effective_auto_reply(user_settings, chat_id)
            is_auto = (auto_reply == CHAT_AUTONOMOUS_SENTINEL)
            
            gen_kwargs = {
                "system_prompt": build_draft_prompt(
                    has_history=False,
                    custom_prompt=user_settings.get("custom_prompt", ""),
                    style=style,
                    local_time_str=get_local_time_string(tz_offset),
                    language_code=u.language_code or DEFAULT_LANGUAGE_CODE,
                    is_autonomous=is_auto,
                ),
            }
            model = get_effective_model(user_settings, style)
            if model:
                gen_kwargs["model"] = model
            
            if instruction.strip():
                user_msg_text = f"INSTRUCTION: {instruction}"
            else:
                user_msg_text = await get_system_message(u.language_code, "cold_outreach_default_instruction")

            draft_text = await generate_response(user_msg_text, **gen_kwargs)
            
            if draft_text and draft_text.strip():
                draft_text = draft_text.strip()
                dynamic_delay = None
                skip_auto_reply = False
                
                if is_auto:
                    draft_text, extracted_delay, is_manual = extract_autonomous_delay(draft_text)
                    if is_manual:
                        skip_auto_reply = True
                    elif extracted_delay is None:
                        dynamic_delay = calculate_fallback_delay()
                    else:
                        dynamic_delay = extracted_delay
                
                await register_bot_draft_and_schedule(
                    u.id, chat_id, draft_text, user_settings, style,
                    skip_auto_reply=skip_auto_reply, dynamic_delay=dynamic_delay
                )
                
                success_msg = (await get_system_message(u.language_code, "cold_outreach_success")).format(username=raw_username)
                await status_msg.edit_text(success_msg)
            else:
                error_msg = await get_system_message(u.language_code, "error")
                await status_msg.edit_text(error_msg)
            return

        # История сообщений в чате с ботом (хранится в context.chat_data)
        history: list[dict] = context.chat_data.setdefault("history", [])

        if DEBUG_PRINT:
            print(
                f"{get_timestamp()} [BOT] Text from user {u.id}: "
                f"{len(message_text)} chars, history: {len(history)} messages"
            )

        # Читаем настройки пользователя для выбора модели и стиля
        user_settings = (user or {}).get("settings") or {}
        style = user_settings.get("style")
        model = get_effective_model(user_settings, style)
        effective_model = model or FREE_LLM_MODEL

        # Генерируем ответ через OpenRouter с историей и стилем
        kwargs: dict = {"chat_history": history[-MAX_CONTEXT_MESSAGES:]}
        full_name = u.first_name or ""
        if u.last_name:
            full_name += f" {u.last_name}"
        tz_offset = user_settings.get("tz_offset", 0) or 0
        kwargs["system_prompt"] = build_bot_chat_prompt(
            style=style, 
            user_name=full_name,
            local_time_str=get_local_time_string(tz_offset),
        )
        kwargs["reasoning_effort"] = MODEL_REASONING_EFFORT.get(effective_model, "medium")
        if model:
            kwargs["model"] = model

        # RAG: подтягиваем релевантную документацию для вопросов о боте
        rag_context = await retrieve_context(message_text)
        if rag_context:
            kwargs["system_prompt"] += f"\n\nRELEVANT DOCUMENTATION:\n{rag_context}"

        response_text = await generate_response(message_text, **kwargs)

        # Сохраняем в историю
        history.append({"role": "user", "content": message_text})
        history.append({"role": "assistant", "content": response_text})

        # Обрезаем историю, чтобы не разрастался
        if len(history) > MAX_CONTEXT_MESSAGES:
            del history[: len(history) - MAX_CONTEXT_MESSAGES]

        # Отправляем ответ
        await m.reply_text(response_text)
        dash_stats.record_bot_reply()

        if DEBUG_PRINT:
            print(f"{get_timestamp()} [BOT] Response sent to user {u.id}")

    except Exception as e:
        print(f"{get_timestamp()} [BOT] ERROR generating response for user {u.id}: {e}")
        traceback.print_exc()
        error_msg = await get_system_message(u.language_code, "error")
        await m.reply_text(error_msg or SYSTEM_MESSAGES["error"])
