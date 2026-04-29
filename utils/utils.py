# utils/utils.py — Утилиты общего назначения (форматирование, декораторы, стили)

import asyncio
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Callable

from config import (
    AUTO_REPLY_OPTIONS,
    AUTONOMOUS_FALLBACK_DELAY,
    CHAT_IGNORED_SENTINEL,
    DEFAULT_PRO_MODEL,
    DEFAULT_STYLE,
    FOLLOW_UP_OPTIONS,
    STYLE_PRO_MODELS,
)


def get_effective_pro_model(settings: dict) -> bool:
    """Возвращает флаг PRO-модели с учётом дефолта из config."""
    return settings.get("pro_model", DEFAULT_PRO_MODEL)


def get_effective_model(settings: dict, style: str) -> str | None:
    """Возвращает имя PRO-модели для стиля или None (FREE).

    Args:
        settings: Настройки пользователя
        style: Ключ стиля (уже resolved через get_effective_style)

    Returns:
        Строка модели (e.g. 'openai/gpt-5.4') или None
    """
    if not get_effective_pro_model(settings):
        return None
    model = STYLE_PRO_MODELS.get(style)
    if model is None:
        print(f"{get_timestamp()} WARNING: style {style!r} not in STYLE_PRO_MODELS, using default")
        model = STYLE_PRO_MODELS[DEFAULT_STYLE]
    return model


def get_timestamp() -> str:
    """Возвращает текущее время в формате для логов."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_local_time_string(tz_offset: float = 0) -> str:
    """Возвращает текущее локальное время пользователя для промпта."""
    local_time = datetime.now(timezone.utc) + timedelta(hours=tz_offset)
    return local_time.strftime("%Y-%m-%d %H:%M (%A)")


_TYPING_INTERVAL = 4  # Telegram сбрасывает индикатор ~5 сек; обновляем каждые 4
_USER_UPDATE_LOCKS: dict[int, asyncio.Lock] = {}
_USER_UPDATE_LOCK_COUNTS: defaultdict[int, int] = defaultdict(int)


@asynccontextmanager
async def keep_typing(bot, chat_id: int):
    """Контекст-менеджер: удерживает индикатор 'печатает...' до выхода из блока."""
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    async def _loop() -> None:
        try:
            while True:
                await asyncio.sleep(_TYPING_INTERVAL)
                try:
                    await bot.send_chat_action(chat_id=chat_id, action="typing")
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def typing_action(func: Callable) -> Callable:
    """Декоратор: удерживает индикатор 'печатает...' на всё время выполнения обработчика."""
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        async with keep_typing(context.bot, update.effective_chat.id):
            return await func(update, context, *args, **kwargs)
    return wrapper


@asynccontextmanager
async def serialize_user_update_by_id(user_id: int | None):
    """Сериализует stateful Bot API handlers для одного пользователя."""
    if user_id is None:
        yield
        return

    # No race condition: get → is None → set runs in a single coroutine step (no await).
    lock = _USER_UPDATE_LOCKS.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _USER_UPDATE_LOCKS[user_id] = lock

    _USER_UPDATE_LOCK_COUNTS[user_id] += 1
    try:
        async with lock:
            yield
    finally:
        _USER_UPDATE_LOCK_COUNTS[user_id] -= 1
        if _USER_UPDATE_LOCK_COUNTS[user_id] == 0:
            _USER_UPDATE_LOCK_COUNTS.pop(user_id, None)
            _USER_UPDATE_LOCKS.pop(user_id, None)


def serialize_user_updates(func: Callable) -> Callable:
    """Декоратор: обрабатывает апдейты одного пользователя строго по очереди."""
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        effective_user = getattr(update, "effective_user", None)
        user_id = getattr(effective_user, "id", None)
        async with serialize_user_update_by_id(user_id):
            return await func(update, context, *args, **kwargs)
    return wrapper


def format_profile(info: dict | None, label: str) -> str:
    """Форматирует профиль участника в строку для промпта."""
    if not info:
        return label

    name = info.get("first_name", "")
    last = info.get("last_name")
    if last:
        name += f" {last}"

    return name if name else label


_DELAY_PATTERN = re.compile(
    r"\[DELAY:\s*(MANUAL|\d+)\s*(s|sec|seconds?|m|min|minutes?)?[^\[\]]*\]?",
    re.IGNORECASE,
)


def extract_autonomous_delay(text: str) -> tuple[str, int | None, bool]:
    """Извлекает автономную задержку из текста ответа LLM.

    Ищет тег [DELAY: X] или [DELAY: MANUAL] в любом месте текста (без учета регистра).
    Поддерживает суффиксы единиц: 's'/'sec'/'seconds' (по умолчанию), 'm'/'min'/'minutes'
    (умножается на 60). Закрывающая скобка опциональна, чтобы вытаскивать значение
    даже из «сломанных» тегов вида '[DELAY: 15ждууу [DELAY: 15]'.

    Returns:
        (clean_text, delay_seconds, is_manual)
    """
    if not text:
        return text, None, False

    match = _DELAY_PATTERN.search(text)
    if not match:
        return text, None, False

    value = match.group(1).upper()
    suffix = (match.group(2) or "").lower()
    clean_text = _DELAY_PATTERN.sub("", text).strip()

    if value == "MANUAL":
        return clean_text, None, True

    try:
        seconds = int(value)
    except ValueError:
        return clean_text, None, False

    if suffix.startswith("m"):
        seconds *= 60
    return clean_text, seconds, False


def calculate_fallback_delay() -> int:
    """Запасная задержка (секунды), если ИИ забыл вернуть тег DELAY."""
    return AUTONOMOUS_FALLBACK_DELAY


def format_participants(
    user_info: dict | None = None,
    opponent_info: dict | None = None,
    chat_history: list[dict] | None = None,
) -> str:
    """Собирает блок 'PARTICIPANTS:' с профилями и bio участников.

    Используется как для чатов с историей (`format_chat_history`), так и для cold
    outreach без истории, чтобы bio собеседника единообразно попадало в контекст
    модели в одном и том же формате.

    Args:
        user_info: Информация о владельце сессии (опционально)
        opponent_info: Информация об оппоненте (опционально)
        chat_history: История сообщений для дополнения списка собеседников
            (если есть несколько участников в группе)

    Returns:
        Строку вида:
            PARTICIPANTS:
            You: Name
            You bio: ...
            Them: Name1, Name2
            Them bio: ...
    """
    user_profile = format_profile(user_info, "You")
    lines = [f"You: {user_profile}"]

    if user_info and user_info.get("bio"):
        lines.append(f"You bio: {user_info['bio']}")

    them_names: list[str] = []
    seen_names: set[str] = set()
    if opponent_info:
        opp_profile = format_profile(opponent_info, "Them")
        seen_names.add(opponent_info.get("first_name", ""))
        them_names.append(opp_profile)

    for msg in (chat_history or []):
        if msg["role"] != "user" and msg.get("name") and msg["name"] not in seen_names:
            seen_names.add(msg["name"])
            full_name = msg["name"]
            if msg.get("last_name"):
                full_name += f" {msg['last_name']}"
            them_names.append(full_name)

    if them_names:
        lines.append("Them: " + ", ".join(them_names))
    else:
        lines.append("Them: Them")

    if opponent_info and opponent_info.get("bio"):
        lines.append(f"Them bio: {opponent_info['bio']}")

    return "PARTICIPANTS:\n" + "\n".join(lines)


def format_chat_history(
    chat_history: list[dict],
    user_info: dict | None = None,
    opponent_info: dict | None = None,
    tz_offset: float = 0,
) -> str:
    """Форматирует историю чата с профилями участников для AI-промпта.

    Args:
        chat_history: Список сообщений [{role, text, date?, name?}]
        user_info: Информация о пользователе
        opponent_info: Информация об оппоненте
        tz_offset: Смещение часового пояса пользователя (часы, напр. 5.5)

    Возвращает строку вида:
        PARTICIPANTS:
        You: Name
        You bio: ... (если задано)
        Them: Name
        Them bio: ... (если задано)

        CHAT HISTORY:
        [2026-03-14 14:30] Name: text

    Если `chat_history` пуст, возвращается только блок PARTICIPANTS — это
    используется в Cold Outreach, где истории ещё нет.
    """
    you = format_profile(user_info, "You")
    them = format_profile(opponent_info, "Them")

    parts = [format_participants(user_info, opponent_info, chat_history)]

    tz_delta = timedelta(hours=tz_offset) if tz_offset else timedelta()

    # Форматируем историю в текст для AI
    formatted = []
    for msg in chat_history:
        # В группах у каждого сообщения своё имя отправителя
        if msg["role"] == "user":
            name = you
        else:
            name = msg.get("name") or them
            if msg.get("last_name"):
                name += f" {msg['last_name']}"
        date = msg.get("date")
        if date:
            local_date = date + tz_delta
            ts = local_date.strftime("%Y-%m-%d %H:%M")
            formatted.append(f"[{ts}] {name}: {msg['text']}")
        else:
            formatted.append(f"{name}: {msg['text']}")

    if formatted:
        parts.append("CHAT HISTORY:\n" + "\n".join(formatted))

    return "\n\n".join(parts)


def normalize_auto_reply(value: object) -> int | None:
    """Возвращает валидный auto_reply или None (OFF)."""
    return value if value in AUTO_REPLY_OPTIONS else None


def get_effective_style(settings: dict, chat_id: int | None = None) -> str:
    """Возвращает стиль для конкретного чата (per-chat override → глобальный дефолт).

    Args:
        settings: Настройки пользователя
        chat_id: ID чата (None → глобальный стиль)

    Returns:
        Ключ стиля (по умолчанию 'userlike')
    """
    if chat_id is not None:
        chat_styles = settings.get("chat_styles") or {}
        per_chat = chat_styles.get(str(chat_id))
        if per_chat:
            return per_chat
    return settings.get("style") or DEFAULT_STYLE


def get_effective_auto_reply(settings: dict, chat_id: int | None = None) -> int | None:
    """Возвращает auto_reply для конкретного чата (per-chat override → глобальный дефолт).

    Args:
        settings: Настройки пользователя
        chat_id: ID чата (None → глобальный auto_reply)

    Returns:
        Секунды автоответа или None (OFF)
    """
    if chat_id is not None:
        chat_auto_replies = settings.get("chat_auto_replies") or {}
        chat_key = str(chat_id)
        if chat_key in chat_auto_replies:
            per_chat = chat_auto_replies[chat_key]
            # 0 = явно выключено (OFF), None в JSON невозможен
            return None if per_chat == 0 else normalize_auto_reply(per_chat)
    return normalize_auto_reply(settings.get("auto_reply"))


def normalize_follow_up(value: object) -> int | None:
    """Возвращает валидный follow_up или None (OFF)."""
    return value if value in FOLLOW_UP_OPTIONS else None


def get_effective_follow_up(settings: dict, chat_id: int | None = None) -> int | None:
    """Возвращает follow_up таймер для конкретного чата (per-chat override → глобальный дефолт).

    Args:
        settings: Настройки пользователя
        chat_id: ID чата (None → глобальный follow_up)

    Returns:
        Секунды follow-up или None (OFF)
    """
    if chat_id is not None:
        chat_follow_ups = settings.get("chat_follow_ups") or {}
        chat_key = str(chat_id)
        if chat_key in chat_follow_ups:
            per_chat = chat_follow_ups[chat_key]
            # 0 = явно выключено (OFF), None в JSON невозможен
            return None if per_chat == 0 else normalize_follow_up(per_chat)
    return normalize_follow_up(settings.get("follow_up"))


def is_chat_specifically_ignored(settings: dict, chat_id: int) -> bool:
    """Возвращает True, только если на этот конкретный чат установлен 🔇 Ignore."""
    chat_auto_replies = settings.get("chat_auto_replies") or {}
    chat_key = str(chat_id)
    if chat_key in chat_auto_replies:
        return chat_auto_replies[chat_key] == CHAT_IGNORED_SENTINEL
    return False


def is_chat_ignored(settings: dict, chat_id: int) -> bool:
    """Возвращает True, если чат игнорируется (глобальный или per-chat sentinel -1)."""
    if is_chat_specifically_ignored(settings, chat_id):
        return True

    # Решаем по глобальному override, если настройки для чата нет
    chat_auto_replies = settings.get("chat_auto_replies") or {}
    chat_key = str(chat_id)
    if chat_key in chat_auto_replies:
        return False  # Есть явная настройка (и она не Ignore, так как мы проверили выше)

    # Глобальный ignore: если в /settings выбран 🔇 Ignore (-1), 
    # это полностью отключает и автоответы, и генерацию черновиков во всех чатах.
    return normalize_auto_reply(settings.get("auto_reply")) == CHAT_IGNORED_SENTINEL


def get_effective_prompt(settings: dict, chat_id: int | None = None) -> str:
    """Возвращает итоговый промпт: глобальный + per-chat (через \\n).

    Args:
        settings: Настройки пользователя
        chat_id: ID чата (None → только глобальный промпт)

    Returns:
        Конкатенация глобального и per-chat промптов
    """
    global_prompt = settings.get("custom_prompt", "") or ""
    if chat_id is None:
        return global_prompt
    chat_prompts = settings.get("chat_prompts") or {}
    per_chat = chat_prompts.get(str(chat_id), "") or ""
    if global_prompt and per_chat:
        return f"{global_prompt}\n{per_chat}"
    return global_prompt or per_chat

