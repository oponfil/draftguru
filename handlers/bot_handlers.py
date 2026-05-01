# handlers/bot_handlers.py — Обработчики команд Telegram Bot API (/start, on_text)

import asyncio
import json
import re
import traceback

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update, User
from telegram.ext import ContextTypes

from config import (
    CHAT_AUTONOMOUS_SENTINEL,
    CHAT_PROMPT_MAX_LENGTH,
    DEBUG_PRINT,
    DEFAULT_LANGUAGE_CODE,
    EMOJI_TO_STYLE,
    FREE_LLM_MODEL,
    MAX_CONTEXT_MESSAGES,
    MODEL_REASONING_EFFORT,
    USER_PROMPT_MAX_LENGTH,
)
from utils.utils import (
    calculate_fallback_delay,
    extract_autonomous_delay,
    format_chat_history,
    get_effective_auto_reply,
    get_effective_model,
    get_effective_prompt,
    get_local_time_string,
    get_timestamp,
    serialize_user_updates,
    typing_action,
)
from utils.bot_utils import update_user_menu
from utils.telegram_user import ensure_effective_user, upsert_effective_user
from clients.x402gate.openrouter import generate_response
from prompts import build_bot_chat_prompt, build_draft_prompt, format_user_instruction
from logic.rag import retrieve_context
from database.users import (
    get_user,
    update_chat_prompt,
    update_chat_style,
    update_last_msg_at,
    update_tg_rating,
    update_user_settings,
)
from utils.telegram_rating import extract_rating_from_chat
from system_messages import get_system_message, SYSTEM_MESSAGES
from clients import pyrogram_client
from dashboard import stats as dash_stats
from handlers.connect_handler import on_connect
from handlers.pyrogram_handlers import register_bot_draft_and_schedule


VALID_STYLES: frozenset[str] = frozenset(EMOJI_TO_STYLE.values())
# Допускаем username c префиксом ('@', 't.me/', 'https://t.me/') и без — голый ник тоже валиден.
USERNAME_RE = re.compile(
    r"^(?:@|https?://t\.me/|t\.me/)?[a-zA-Z0-9_]{5,32}$",
    flags=re.IGNORECASE,
)

# Локальные лимиты batch cold outreach: используются только в on_json_document.
BATCH_OUTREACH_MAX_FILE_SIZE = 1 * 1024 * 1024  # Макс. размер JSON-файла (1 МБ)
BATCH_OUTREACH_MAX_ITEMS = 100  # Макс. число записей в одном батче


def _opponent_info_from_target_chat(target_chat: dict) -> dict:
    """Достаёт минимальный профиль собеседника из ответа resolve_target_chat."""
    return {
        "first_name": target_chat.get("first_name"),
        "last_name": target_chat.get("last_name"),
        "username": target_chat.get("username"),
        "bio": target_chat.get("bio"),
    }


async def _execute_cold_outreach(
    u: User,
    user: dict | None,
    chat_id: int,
    target_chat: dict,
    instruction: str,
    user_settings: dict,
    style: str,
    custom_prompt: str,
    tz_offset: float,
) -> bool:
    """Генерирует и устанавливает черновик для первого сообщения (Cold Outreach)."""
    auto_reply = get_effective_auto_reply(user_settings, chat_id)
    is_auto = (auto_reply == CHAT_AUTONOMOUS_SENTINEL)

    gen_kwargs = {
        "system_prompt": build_draft_prompt(
            has_history=False,
            custom_prompt=custom_prompt,
            style=style,
            local_time_str=get_local_time_string(tz_offset),
            language_code=u.language_code or DEFAULT_LANGUAGE_CODE,
            is_autonomous=is_auto,
        ),
    }
    model = get_effective_model(user_settings, style)
    if model:
        gen_kwargs["model"] = model

    fallback_text = await get_system_message(u.language_code, "cold_outreach_default_instruction")
    instruction_text = instruction.strip() or fallback_text
    opponent_info = _opponent_info_from_target_chat(target_chat)
    user_msg_text = format_chat_history([], user, opponent_info, tz_offset=tz_offset)
    user_msg_text += format_user_instruction(instruction_text)

    draft_text = await generate_response(user_msg_text, **gen_kwargs)

    if not draft_text or not draft_text.strip():
        return False

    draft_text = draft_text.strip()
    dynamic_delay: int | None = None
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
        skip_auto_reply=skip_auto_reply, dynamic_delay=dynamic_delay,
    )
    return True


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
        username_match = re.match(
            r"^(@[a-zA-Z0-9_]{5,32}|https?://t\.me/[a-zA-Z0-9_]{5,32}|t\.me/[a-zA-Z0-9_]{5,32})(?:\s+(.*))?$",
            message_text.strip(),
            flags=re.IGNORECASE,
        )
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
            effective_custom_prompt = get_effective_prompt(user_settings, chat_id)

            success = await _execute_cold_outreach(
                u, user, chat_id, target_chat, instruction,
                user_settings, style, effective_custom_prompt, tz_offset,
            )

            if success:
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


def _coerce_optional_str(value: object) -> str | None:
    """Превращает значение в строку, если это str/число; иначе None."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


async def _process_batch_item(
    u: User,
    user: dict | None,
    user_settings: dict,
    global_tz_offset: float,
    global_style: str,
    item: dict,
) -> bool:
    """Обрабатывает одну запись из batch-JSON.

    Returns:
        True если черновик создан, иначе False.
    """
    raw_username = _coerce_optional_str(item.get("username"))
    if not raw_username or not USERNAME_RE.match(raw_username.strip()):
        return False

    target_chat = await pyrogram_client.resolve_target_chat(u.id, raw_username.strip())
    if not target_chat:
        return False

    chat_id = target_chat["chat_id"]

    raw_style = _coerce_optional_str(item.get("style"))
    if raw_style and raw_style in VALID_STYLES:
        chat_style = raw_style
        await update_chat_style(u.id, chat_id, chat_style)
    else:
        chat_style = global_style

    raw_prompt = _coerce_optional_str(item.get("prompt"))
    if raw_prompt is not None:
        truncated = raw_prompt.strip()[:CHAT_PROMPT_MAX_LENGTH]
        await update_chat_prompt(u.id, chat_id, truncated or None)

    refreshed = await get_user(u.id)
    refreshed_settings = (refreshed or {}).get("settings") or user_settings
    effective_custom_prompt = get_effective_prompt(refreshed_settings, chat_id)

    instruction = _coerce_optional_str(item.get("instruction")) or ""

    return await _execute_cold_outreach(
        u, user, chat_id, target_chat, instruction,
        refreshed_settings, chat_style, effective_custom_prompt, global_tz_offset,
    )


@typing_action
async def on_json_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик загрузки JSON-файла для массовой генерации черновиков."""
    u = update.effective_user
    m = update.message

    try:
        user = await ensure_effective_user(update)
        asyncio.create_task(update_last_msg_at(u.id))

        if not pyrogram_client.is_active(u.id):
            error_msg = await get_system_message(u.language_code, "cold_outreach_not_connected")
            await m.reply_text(error_msg)
            return

        doc = m.document
        if not doc or not (doc.file_name or "").lower().endswith(".json"):
            return

        if doc.file_size and doc.file_size > BATCH_OUTREACH_MAX_FILE_SIZE:
            too_large_msg = (await get_system_message(u.language_code, "batch_outreach_too_large")).format(
                limit_kb=BATCH_OUTREACH_MAX_FILE_SIZE // 1024,
            )
            await m.reply_text(too_large_msg)
            return

        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()

        try:
            data = json.loads(bytes(file_bytes).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            invalid_msg = await get_system_message(u.language_code, "batch_outreach_invalid")
            await m.reply_text(invalid_msg)
            return

        if not isinstance(data, list) or not data:
            invalid_msg = await get_system_message(u.language_code, "batch_outreach_invalid")
            await m.reply_text(invalid_msg)
            return

        if len(data) > BATCH_OUTREACH_MAX_ITEMS:
            too_many_msg = (await get_system_message(u.language_code, "batch_outreach_too_many_items")).format(
                limit=BATCH_OUTREACH_MAX_ITEMS,
            )
            await m.reply_text(too_many_msg)
            return

        started_msg = await get_system_message(u.language_code, "batch_outreach_started")
        status_msg = await m.reply_text(started_msg)

        success_count = 0
        error_count = 0

        user_settings = (user or {}).get("settings") or {}
        global_tz_offset = user_settings.get("tz_offset", 0) or 0
        global_style = user_settings.get("style", "userlike")

        for index, item in enumerate(data):
            progress_text = f"{started_msg}\n\n⏳ {index + 1} / {len(data)}"
            try:
                await status_msg.edit_text(progress_text)
            except Exception as edit_err:
                if DEBUG_PRINT:
                    print(
                        f"{get_timestamp()} [BOT] WARNING failed to update batch progress "
                        f"for user {u.id}: {edit_err}"
                    )

            if not isinstance(item, dict):
                error_count += 1
                continue

            try:
                created = await _process_batch_item(
                    u, user, user_settings, global_tz_offset, global_style, item,
                )
            except Exception as item_err:
                created = False
                print(
                    f"{get_timestamp()} [BOT] ERROR processing batch item #{index} "
                    f"for user {u.id}: {item_err}"
                )

            if created:
                success_count += 1
            else:
                error_count += 1

        success_msg_template = await get_system_message(u.language_code, "batch_outreach_success")
        success_msg = success_msg_template.format(success_count=success_count, error_count=error_count)
        await status_msg.edit_text(success_msg)

    except Exception as e:
        print(f"{get_timestamp()} [BOT] ERROR processing JSON document for user {u.id}: {e}")
        traceback.print_exc()
        error_msg = await get_system_message(u.language_code, "error")
        await m.reply_text(error_msg or SYSTEM_MESSAGES["error"])
