# clients/pyrogram_client.py — Управление Pyrogram-сессиями пользователей

import asyncio

from pyrogram import Client, filters, raw
from pyrogram.handlers import MessageHandler, RawUpdateHandler

from config import PYROGRAM_API_ID, PYROGRAM_API_HASH, MAX_CONTEXT_MESSAGES, DEBUG_PRINT, VOICE_TRANSCRIPTION_TIMEOUT
from utils.utils import get_timestamp


# Активные Pyrogram-клиенты: {user_id: Client}
_active_clients: dict[int, Client] = {}

# Состояние глобального exception handler event loop-а, который мы временно
# подменяем ради Pyrogram.
_loop_handler_state = {
    "loop": None,
    "previous_handler": None,
}

# Callback для обработки входящих сообщений (устанавливается из bot.py)
_on_new_message_callback = None

# Callback для обработки черновиков (устанавливается из bot.py)
_on_draft_callback = None


def set_message_callback(callback) -> None:
    """Устанавливает callback для обработки входящих сообщений."""
    global _on_new_message_callback
    _on_new_message_callback = callback


def set_draft_callback(callback) -> None:
    """Устанавливает callback для обработки черновиков."""
    global _on_draft_callback
    _on_draft_callback = callback


async def create_client(user_id: int, session_string: str) -> Client:
    """Создаёт Pyrogram Client из session string."""
    client = Client(
        name=f"talkguru_{user_id}",
        api_id=PYROGRAM_API_ID,
        api_hash=PYROGRAM_API_HASH,
        session_string=session_string,
        in_memory=True,
    )
    return client


def _pyrogram_task_exception_handler(loop, context):
    """Обработчик исключений в asyncio-задачах Pyrogram.

    Pyrogram создаёт внутренние Task-и (handle_updates) которые могут
    бросать ValueError при получении update-ов из незнакомых supergroup/channel.
    Логируем как WARNING вместо полного traceback.
    """
    exception = context.get("exception")
    if isinstance(exception, ValueError) and "Peer id invalid" in str(exception):
        print(f"{get_timestamp()} [PYROGRAM] WARNING: {exception} (ignored)")
        return

    # Для всех остальных исключений делегируем предыдущему handler-у,
    # если он был настроен, иначе используем стандартный.
    previous_handler = _loop_handler_state["previous_handler"]
    if previous_handler:
        previous_handler(loop, context)
    else:
        loop.default_exception_handler(context)


def _install_pyrogram_exception_handler(loop) -> None:
    """Устанавливает обёртку над loop exception handler один раз."""
    if (
        _loop_handler_state["loop"] is loop
        and loop.get_exception_handler() is _pyrogram_task_exception_handler
    ):
        return

    _loop_handler_state["previous_handler"] = loop.get_exception_handler()
    loop.set_exception_handler(_pyrogram_task_exception_handler)
    _loop_handler_state["loop"] = loop


def _restore_pyrogram_exception_handler(loop) -> None:
    """Восстанавливает предыдущий loop exception handler."""
    if _loop_handler_state["loop"] is not loop:
        return

    if loop.get_exception_handler() is _pyrogram_task_exception_handler:
        loop.set_exception_handler(_loop_handler_state["previous_handler"])

    _loop_handler_state["previous_handler"] = None
    _loop_handler_state["loop"] = None


async def start_listening(user_id: int, session_string: str) -> bool:
    """Запускает Pyrogram-клиент и слушатель входящих сообщений.

    Args:
        user_id: Telegram user ID
        session_string: Pyrogram session string из БД

    Returns:
        True если запуск успешен
    """
    # Останавливаем предыдущий клиент, если есть
    await stop_listening(user_id)

    try:
        client = await create_client(user_id, session_string)
        loop = asyncio.get_running_loop()

        # Подавляем ValueError: Peer id invalid из внутренних задач Pyrogram
        _install_pyrogram_exception_handler(loop)

        await client.start()

        # Хендлер входящих сообщений (только личные чаты, не от себя)
        async def on_incoming(pyrogram_client: Client, message):
            if _on_new_message_callback:
                await _on_new_message_callback(user_id, pyrogram_client, message)

        client.add_handler(
            MessageHandler(on_incoming, filters.private & filters.incoming)
        )

        # Хендлер черновиков (raw update)
        async def on_raw(client: Client, update, users, chats):
            if isinstance(update, raw.types.UpdateDraftMessage):
                await _handle_draft_update(user_id, update)

        client.add_handler(RawUpdateHandler(on_raw))

        _active_clients[user_id] = client
        print(f"{get_timestamp()} [PYROGRAM] Started listening for user {user_id}")
        return True

    except Exception as e:
        try:
            loop = asyncio.get_running_loop()
            if not _active_clients:
                _restore_pyrogram_exception_handler(loop)
        except RuntimeError:
            pass
        print(f"{get_timestamp()} [PYROGRAM] ERROR starting client for user {user_id}: {e}")
        return False


async def stop_listening(user_id: int) -> bool:
    """Останавливает Pyrogram-клиент пользователя."""
    client = _active_clients.get(user_id)
    if not client:
        return True

    try:
        loop = asyncio.get_running_loop()
        await client.stop()
        _active_clients.pop(user_id, None)
        if not _active_clients:
            _restore_pyrogram_exception_handler(loop)
        print(f"{get_timestamp()} [PYROGRAM] Stopped listening for user {user_id}")
        return True
    except Exception as e:
        print(f"{get_timestamp()} [PYROGRAM] ERROR stopping client for user {user_id}: {e}")
        return False


def is_active(user_id: int) -> bool:
    """Проверяет, активен ли Pyrogram-клиент пользователя."""
    return user_id in _active_clients


async def read_chat_history(user_id: int, chat_id: int, limit: int = MAX_CONTEXT_MESSAGES) -> list[dict]:
    """Читает последние сообщения из чата пользователя.

    Args:
        user_id: Telegram user ID
        chat_id: ID чата для чтения
        limit: Максимальное количество сообщений

    Returns:
        Список сообщений [{role: "user"/"other", text: "..."}]
    """
    client = _active_clients.get(user_id)
    if not client:
        return []

    messages = []
    try:
        async for msg in client.get_chat_history(chat_id, limit=limit):
            if not msg.text:
                continue

            role = "user" if msg.from_user and msg.from_user.id == user_id else "other"
            sender = msg.from_user
            messages.append({
                "role": role,
                "text": msg.text,
                "date": msg.date,
                "name": sender.first_name if sender else None,
                "last_name": sender.last_name if sender else None,
                "username": sender.username if sender else None,
            })

        # Переворачиваем — от старых к новым
        messages.reverse()

        if DEBUG_PRINT:
            print(f"{get_timestamp()} [PYROGRAM] Read {len(messages)} messages from chat {chat_id}")

    except Exception as e:
        print(f"{get_timestamp()} [PYROGRAM] ERROR reading chat {chat_id} for user {user_id}: {e}")

    return messages


async def _handle_draft_update(user_id: int, update: raw.types.UpdateDraftMessage) -> None:
    """Обрабатывает raw UpdateDraftMessage — извлекает chat_id и текст, вызывает callback."""
    if not _on_draft_callback:
        return

    try:
        # Извлекаем chat_id из peer и конвертируем в стандартный Telegram формат:
        # PeerUser.user_id → положительный (без изменений)
        # PeerChat.chat_id → отрицательный (-chat_id)
        # PeerChannel.channel_id → отрицательный с префиксом -100 (-100channel_id)
        peer = update.peer
        if hasattr(peer, "user_id"):
            chat_id = peer.user_id
        elif hasattr(peer, "chat_id"):
            chat_id = -peer.chat_id
        elif hasattr(peer, "channel_id"):
            chat_id = int(f"-100{peer.channel_id}")
        else:
            return

        # Извлекаем текст черновика (может быть пустым при очистке)
        draft = update.draft
        draft_text = getattr(draft, "message", "") or ""

        if DEBUG_PRINT:
            print(
                f"{get_timestamp()} [PYROGRAM] Draft update for user {user_id} "
                f"in chat {chat_id}: {len(draft_text)} chars"
            )

        await _on_draft_callback(user_id, chat_id, draft_text.strip())

    except Exception as e:
        print(f"{get_timestamp()} [PYROGRAM] ERROR handling draft update for user {user_id}: {e}")


async def set_draft(user_id: int, chat_id: int, text: str) -> bool:
    """Устанавливает черновик (draft) в чате пользователя.

    Args:
        user_id: Telegram user ID
        chat_id: ID чата
        text: Текст черновика

    Returns:
        True если установка успешна
    """
    client = _active_clients.get(user_id)
    if not client:
        return False

    try:
        peer = await client.resolve_peer(chat_id)
        await client.invoke(
            raw.functions.messages.SaveDraft(
                peer=peer,
                message=text,
            )
        )

        if DEBUG_PRINT:
            print(f"{get_timestamp()} [PYROGRAM] Draft set in chat {chat_id} for user {user_id}")
        return True

    except Exception as e:
        print(f"{get_timestamp()} [PYROGRAM] ERROR setting draft in chat {chat_id}: {e}")
        return False


async def send_message(user_id: int, chat_id: int, text: str) -> bool:
    """Отправляет сообщение от имени пользователя через Pyrogram.

    Args:
        user_id: Telegram user ID
        chat_id: ID чата
        text: Текст сообщения

    Returns:
        True если отправка успешна
    """
    client = _active_clients.get(user_id)
    if not client:
        return False

    try:
        await client.send_message(chat_id, text)

        if DEBUG_PRINT:
            print(f"{get_timestamp()} [PYROGRAM] Message sent in chat {chat_id} for user {user_id}")
        return True

    except Exception as e:
        print(f"{get_timestamp()} [PYROGRAM] ERROR sending message in chat {chat_id}: {e}")
        return False


async def transcribe_voice(user_id: int, chat_id: int, msg_id: int) -> str | None:
    """Транскрибирует голосовое сообщение через Telegram Premium TranscribeAudio.

    Args:
        user_id: Telegram user ID
        chat_id: ID чата
        msg_id: ID сообщения с голосовым

    Returns:
        Текст транскрипции или None при ошибке
    """
    client = _active_clients.get(user_id)
    if not client:
        return None

    try:
        peer = await client.resolve_peer(chat_id)
        result = await client.invoke(
            raw.functions.messages.TranscribeAudio(
                peer=peer,
                msg_id=msg_id,
            )
        )

        # Если транскрипция готова сразу
        if not result.pending:
            if DEBUG_PRINT:
                print(f"{get_timestamp()} [PYROGRAM] Transcribed voice in chat {chat_id}: {len(result.text)} chars")
            return result.text or None

        # Ждём UpdateTranscribedAudio через polling
        final_text = result.text or ""

        deadline = asyncio.get_event_loop().time() + VOICE_TRANSCRIPTION_TIMEOUT
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1)
            # Повторяем запрос — Telegram вернёт обновлённый результат
            try:
                result = await client.invoke(
                    raw.functions.messages.TranscribeAudio(
                        peer=peer,
                        msg_id=msg_id,
                    )
                )
                if not result.pending:
                    final_text = result.text or ""
                    break
                final_text = result.text or final_text
            except Exception:
                break

        if final_text:
            if DEBUG_PRINT:
                print(f"{get_timestamp()} [PYROGRAM] Transcribed voice in chat {chat_id}: {len(final_text)} chars")
            return final_text

        return None

    except Exception as e:
        error_str = str(e)
        if "PREMIUM_ACCOUNT_REQUIRED" in error_str:
            print(f"{get_timestamp()} [PYROGRAM] WARNING: voice transcription requires Premium in chat {chat_id}")
        else:
            print(f"{get_timestamp()} [PYROGRAM] ERROR transcribing voice in chat {chat_id}: {e}")
        return None
