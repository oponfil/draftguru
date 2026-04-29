# tests/test_bot.py — Тесты для bot.py и handlers/bot_handlers.py

import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

import bot as bot_module
import utils.utils as utils_module
from handlers.bot_handlers import (
    _process_batch_item,
    on_json_document,
    on_start,
    on_start_connect_callback,
    on_text,
)
from bot import on_error


class TestOnStart:
    """Тесты для on_start()."""

    @pytest.mark.asyncio
    async def test_upserts_user(self, mock_update, mock_context):
        """Сохраняет пользователя в БД."""
        with patch("handlers.bot_handlers.upsert_effective_user", new_callable=AsyncMock, return_value=True) as mock_upsert, \
             patch("handlers.bot_handlers.update_tg_rating", new_callable=AsyncMock), \
             patch("handlers.bot_handlers.extract_rating_from_chat", return_value=None), \
             patch("handlers.bot_handlers.get_system_message", new_callable=AsyncMock, return_value="Hi!"), \
             patch("handlers.bot_handlers.update_user_menu", new_callable=AsyncMock):

            await on_start(mock_update, mock_context)

        mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_sends_greeting(self, mock_update, mock_context):
        """Отправляет приветствие на языке пользователя (с кнопкой Connect)."""
        with patch("handlers.bot_handlers.upsert_effective_user", new_callable=AsyncMock, return_value=True), \
             patch("handlers.bot_handlers.update_tg_rating", new_callable=AsyncMock), \
             patch("handlers.bot_handlers.extract_rating_from_chat", return_value=None), \
             patch("handlers.bot_handlers.get_system_message", new_callable=AsyncMock, return_value="Привет!"), \
             patch("handlers.bot_handlers.update_user_menu", new_callable=AsyncMock), \
             patch("handlers.bot_handlers.pyrogram_client") as mock_pc:
            mock_pc.is_active.return_value = False

            await on_start(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert call_args.args[0] == "Привет!"
        # Кнопка Connect присутствует
        assert call_args.kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_updates_tg_rating(self, mock_update, mock_context):
        """Обновляет tg_rating через getChat."""
        with patch("handlers.bot_handlers.upsert_effective_user", new_callable=AsyncMock, return_value=True), \
             patch("handlers.bot_handlers.update_tg_rating", new_callable=AsyncMock) as mock_rating, \
             patch("handlers.bot_handlers.extract_rating_from_chat", return_value=5), \
             patch("handlers.bot_handlers.get_system_message", new_callable=AsyncMock, return_value="Hi!"), \
             patch("handlers.bot_handlers.update_user_menu", new_callable=AsyncMock):

            await on_start(mock_update, mock_context)

        mock_rating.assert_called_once_with(mock_update.effective_user.id, 5)

    @pytest.mark.asyncio
    async def test_updates_user_menu(self, mock_update, mock_context):
        """Устанавливает меню команд с учётом статуса подключения."""
        with patch("handlers.bot_handlers.upsert_effective_user", new_callable=AsyncMock, return_value=True), \
             patch("handlers.bot_handlers.update_tg_rating", new_callable=AsyncMock), \
             patch("handlers.bot_handlers.extract_rating_from_chat", return_value=None), \
             patch("handlers.bot_handlers.get_system_message", new_callable=AsyncMock, return_value="Hi!"), \
             patch("handlers.bot_handlers.update_user_menu", new_callable=AsyncMock) as mock_menu, \
             patch("handlers.bot_handlers.pyrogram_client") as mock_pc:
            mock_pc.is_active.return_value = False

            await on_start(mock_update, mock_context)

        mock_menu.assert_called_once_with(
            mock_context.bot, mock_update.effective_user.id,
            mock_update.effective_user.language_code, False
        )


class TestOnStartConnectCallback:
    """Тесты для on_start_connect_callback()."""

    @pytest.mark.asyncio
    async def test_delegates_to_on_connect_without_deadlock(self, mock_update, mock_context):
        """Колбэк с /start делегирует в on_connect и не застревает на повторном lock."""
        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_reply_markup = AsyncMock()

        with patch("handlers.bot_handlers.on_connect", new_callable=AsyncMock) as mock_on_connect:
            await asyncio.wait_for(on_start_connect_callback(mock_update, mock_context), timeout=0.2)

        mock_on_connect.assert_awaited_once_with(mock_update, mock_context)


class TestOnText:
    """Тесты для on_text()."""

    @pytest.mark.asyncio
    async def test_empty_text_returns_early(self, mock_update, mock_context):
        """Пустой текст → ранний return."""
        mock_update.message.text = "   "

        with patch("handlers.bot_handlers.update_last_msg_at", new_callable=AsyncMock) as mock_update_msg:
            await on_text(mock_update, mock_context)

        mock_update_msg.assert_not_called()

    @pytest.mark.asyncio
    async def test_generates_and_sends_response(self, mock_update, mock_context):
        """Генерирует ответ и отправляет."""
        mock_update.message.text = "Привет!"

        with patch("handlers.bot_handlers.ensure_effective_user", new_callable=AsyncMock, return_value={"settings": {}}), \
             patch("handlers.bot_handlers.update_last_msg_at", new_callable=AsyncMock), \
             patch("handlers.bot_handlers.generate_response", new_callable=AsyncMock, return_value="Ответ"):

            await on_text(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_with("Ответ")

    @pytest.mark.asyncio
    async def test_passes_recent_history_to_model(self, mock_update, mock_context):
        """Передаёт в модель только последние сообщения из chat_data."""
        mock_update.message.text = "Новый вопрос"
        mock_context.chat_data["history"] = [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
        ]

        with patch("handlers.bot_handlers.MAX_CONTEXT_MESSAGES", 2), \
             patch("handlers.bot_handlers.ensure_effective_user", new_callable=AsyncMock, return_value={"settings": {"pro_model": False}}), \
             patch("handlers.bot_handlers.update_last_msg_at", new_callable=AsyncMock), \
             patch("handlers.bot_handlers.generate_response", new_callable=AsyncMock, return_value="Ответ") as mock_generate:
            await on_text(mock_update, mock_context)

        mock_generate.assert_called_once_with(
            "Новый вопрос",
            chat_history=[
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
            ],
            system_prompt=ANY,
            reasoning_effort=ANY,
        )
        assert mock_context.chat_data["history"] == [
            {"role": "user", "content": "Новый вопрос"},
            {"role": "assistant", "content": "Ответ"},
        ]

    @pytest.mark.asyncio
    async def test_uses_style_pro_model(self, mock_update, mock_context):
        """pro_model + style='seducer' → модель из STYLE_PRO_MODELS['seducer']."""
        mock_update.message.text = "Hello"

        with patch("handlers.bot_handlers.ensure_effective_user", new_callable=AsyncMock, return_value={"settings": {"pro_model": True, "style": "seducer"}}), \
             patch("handlers.bot_handlers.update_last_msg_at", new_callable=AsyncMock), \
             patch("handlers.bot_handlers.generate_response", new_callable=AsyncMock, return_value="Reply") as mock_generate:
            await on_text(mock_update, mock_context)

        call_kwargs = mock_generate.call_args.kwargs
        assert call_kwargs["model"] == "deepseek/deepseek-v4-pro"
        assert call_kwargs["reasoning_effort"] == "medium"

    @pytest.mark.asyncio
    async def test_new_user_empty_settings_gets_default_pro_model(self, mock_update, mock_context):
        """Новый пользователь ({}) → PRO-модель по DEFAULT_PRO_MODEL."""
        mock_update.message.text = "Hello"

        with patch("handlers.bot_handlers.ensure_effective_user", new_callable=AsyncMock, return_value={"settings": {}}), \
             patch("handlers.bot_handlers.update_last_msg_at", new_callable=AsyncMock), \
             patch("handlers.bot_handlers.generate_response", new_callable=AsyncMock, return_value="Reply") as mock_generate, \
             patch("utils.utils.DEFAULT_PRO_MODEL", True):
            await on_text(mock_update, mock_context)

        call_kwargs = mock_generate.call_args.kwargs
        assert "model" in call_kwargs, "Empty settings should use PRO model by default"

    @pytest.mark.asyncio
    async def test_style_included_in_system_prompt(self, mock_update, mock_context):
        """Стиль общения включается в system_prompt."""
        mock_update.message.text = "Hello"

        with patch("handlers.bot_handlers.ensure_effective_user", new_callable=AsyncMock, return_value={"settings": {"style": "paranoid"}}), \
             patch("handlers.bot_handlers.update_last_msg_at", new_callable=AsyncMock), \
             patch("handlers.bot_handlers.generate_response", new_callable=AsyncMock, return_value="Reply") as mock_generate:
            await on_text(mock_update, mock_context)

        call_kwargs = mock_generate.call_args.kwargs
        assert "Paranoid Guru" in call_kwargs["system_prompt"]
        assert "DraftGuru" in call_kwargs["system_prompt"]

    @pytest.mark.asyncio
    async def test_no_style_uses_base_prompt(self, mock_update, mock_context):
        """Без стиля — базовый BOT_PROMPT без дополнений."""
        mock_update.message.text = "Hello"

        with patch("handlers.bot_handlers.ensure_effective_user", new_callable=AsyncMock, return_value={"settings": {}}), \
             patch("handlers.bot_handlers.update_last_msg_at", new_callable=AsyncMock), \
             patch("handlers.bot_handlers.generate_response", new_callable=AsyncMock, return_value="Reply") as mock_generate:
            await on_text(mock_update, mock_context)

        call_kwargs = mock_generate.call_args.kwargs
        assert "DraftGuru" in call_kwargs["system_prompt"]
        assert "COMMUNICATION STYLE" not in call_kwargs["system_prompt"]

    @pytest.mark.asyncio
    async def test_error_sends_error_message(self, mock_update, mock_context):
        """Ошибка генерации → отправляет error message."""
        mock_update.message.text = "Test"

        with patch("handlers.bot_handlers.ensure_effective_user", new_callable=AsyncMock, return_value={"settings": {}}), \
             patch("handlers.bot_handlers.update_last_msg_at", new_callable=AsyncMock), \
             patch("handlers.bot_handlers.generate_response", new_callable=AsyncMock, side_effect=Exception("API fail")), \
             patch("handlers.bot_handlers.get_system_message", new_callable=AsyncMock, return_value="Ошибка"):

            await on_text(mock_update, mock_context)

        mock_update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_updates_last_msg_at(self, mock_update, mock_context):
        """Обновляет last_msg_at."""
        mock_update.message.text = "Hello"

        with patch("handlers.bot_handlers.ensure_effective_user", new_callable=AsyncMock, return_value={"settings": {}}), \
             patch("handlers.bot_handlers.update_last_msg_at", new_callable=AsyncMock) as mock_update_msg, \
             patch("handlers.bot_handlers.generate_response", new_callable=AsyncMock, return_value="Reply"):

            await on_text(mock_update, mock_context)

        mock_update_msg.assert_called_once_with(mock_update.effective_user.id)

    @pytest.mark.asyncio
    async def test_prompt_save_failure_sends_error_and_keeps_waiting_state(self, mock_update, mock_context):
        """При сбое сохранения промпта не показывает ложный успех."""
        mock_update.message.text = "Будь короче"
        mock_context.user_data["awaiting_prompt"] = True

        with patch("handlers.bot_handlers.update_user_settings", new_callable=AsyncMock, return_value=False), \
             patch("handlers.bot_handlers.get_system_message", new_callable=AsyncMock, return_value="Ошибка"):
            await on_text(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once_with("Ошибка")
        assert mock_context.user_data["awaiting_prompt"] is True

    @pytest.mark.asyncio
    async def test_prompt_too_long_is_truncated_saved_and_reported(self, mock_update, mock_context):
        """Слишком длинный промпт обрезается, сохраняется и сообщает об этом."""
        mock_update.message.text = "A" * 601
        mock_context.user_data["awaiting_prompt"] = True

        with patch("handlers.bot_handlers.USER_PROMPT_MAX_LENGTH", 600), \
             patch("handlers.bot_handlers.update_user_settings", new_callable=AsyncMock, return_value=True) as mock_update_settings, \
             patch("handlers.bot_handlers.get_system_message", new_callable=AsyncMock, return_value="Промпт обрезан и сохранён"):
            await on_text(mock_update, mock_context)

        mock_update_settings.assert_called_once_with(
            mock_update.effective_user.id,
            {"custom_prompt": "A" * 600},
        )
        mock_update.message.reply_text.assert_called_once_with("Промпт обрезан и сохранён")
        assert "awaiting_prompt" not in mock_context.user_data

    @pytest.mark.asyncio
    async def test_saving_global_prompt_clears_stale_chat_prompt_state(self, mock_update, mock_context):
        """Успешное сохранение глобального промпта очищает и stale per-chat awaiting."""
        mock_update.message.text = "Будь короче"
        mock_context.user_data["awaiting_prompt"] = True
        mock_context.user_data["awaiting_chat_prompt"] = 100

        with patch("handlers.bot_handlers.update_user_settings", new_callable=AsyncMock, return_value=True), \
             patch("handlers.bot_handlers.get_system_message", new_callable=AsyncMock, return_value="Сохранено"):
            await on_text(mock_update, mock_context)

        assert "awaiting_prompt" not in mock_context.user_data
        assert "awaiting_chat_prompt" not in mock_context.user_data

    @pytest.mark.asyncio
    async def test_saving_chat_prompt_clears_stale_global_prompt_state(self, mock_update, mock_context):
        """Успешное сохранение per-chat промпта очищает stale awaiting_prompt."""
        mock_update.message.text = "Будь формальнее"
        mock_context.user_data["awaiting_prompt"] = True
        mock_context.user_data["awaiting_chat_prompt"] = 100

        with patch("handlers.bot_handlers.update_chat_prompt", new_callable=AsyncMock, return_value=True), \
             patch("handlers.bot_handlers.get_system_message", new_callable=AsyncMock, return_value="Сохранено"):
            await on_text(mock_update, mock_context)

        assert "awaiting_prompt" not in mock_context.user_data
        assert "awaiting_chat_prompt" not in mock_context.user_data

    @pytest.mark.asyncio
    async def test_empty_chat_prompt_is_treated_as_clear(self, mock_update, mock_context):
        """Пустой per-chat промпт очищает настройку вместо сохранения пустой строки."""
        mock_update.message.text = "   "
        mock_context.user_data["awaiting_chat_prompt"] = 100

        with patch("handlers.bot_handlers.update_chat_prompt", new_callable=AsyncMock, return_value=True) as mock_update_prompt, \
             patch("handlers.bot_handlers.get_system_message", new_callable=AsyncMock, return_value="Промпт очищен"):
            await on_text(mock_update, mock_context)

        mock_update_prompt.assert_called_once_with(
            mock_update.effective_user.id,
            100,
            None,
        )
        mock_update.message.reply_text.assert_called_once_with("Промпт очищен")
        assert "awaiting_chat_prompt" not in mock_context.user_data


class TestOnError:
    """Тесты для on_error()."""

    @pytest.mark.asyncio
    async def test_does_not_crash(self, mock_context):
        """Обработчик ошибок не падает."""
        mock_context.error = Exception("Test error")

        # Не должно бросить исключение
        await on_error(MagicMock(), mock_context)


class TestSerializeUserUpdates:
    """Тесты для serialize_user_updates()."""

    @pytest.mark.asyncio
    async def test_runs_same_user_updates_sequentially_and_cleans_up(self):
        started = asyncio.Event()
        release_first = asyncio.Event()
        execution_order: list[str] = []

        @utils_module.serialize_user_updates
        async def handler(update, context):
            execution_order.append(f"start-{update.effective_user.id}")
            if len(execution_order) == 1:
                started.set()
                await release_first.wait()
            execution_order.append(f"end-{update.effective_user.id}")

        update_one = MagicMock()
        update_one.effective_user.id = 123
        update_two = MagicMock()
        update_two.effective_user.id = 123
        context = MagicMock()

        first_task = asyncio.create_task(handler(update_one, context))
        await started.wait()
        second_task = asyncio.create_task(handler(update_two, context))
        await asyncio.sleep(0)

        assert execution_order == ["start-123"]

        release_first.set()
        await asyncio.gather(first_task, second_task)

        assert execution_order == ["start-123", "end-123", "start-123", "end-123"]
        assert utils_module._USER_UPDATE_LOCKS == {}
        assert dict(utils_module._USER_UPDATE_LOCK_COUNTS) == {}


class TestMain:
    """Тесты для main()."""

    def test_registers_handlers_for_private_chats_only(self):
        fake_builder = MagicMock()
        fake_app = MagicMock()

        fake_builder.token.return_value = fake_builder
        fake_builder.read_timeout.return_value = fake_builder
        fake_builder.concurrent_updates.return_value = fake_builder
        fake_builder.post_init.return_value = fake_builder
        fake_builder.build.return_value = fake_app

        command_handlers = []
        message_handlers = []

        def command_handler_stub(*args, **kwargs):
            command_handlers.append((args, kwargs))
            return MagicMock()

        def message_handler_stub(*args, **kwargs):
            message_handlers.append((args, kwargs))
            return MagicMock()

        with patch("bot.Application.builder", return_value=fake_builder), \
             patch("bot.CommandHandler", side_effect=command_handler_stub), \
             patch("bot.MessageHandler", side_effect=message_handler_stub), \
             patch("bot.CallbackQueryHandler", return_value=MagicMock()), \
             patch("bot.pyrogram_client") as mock_pc:
            bot_module.main()

        assert len(command_handlers) == 7
        assert len(message_handlers) == 3
        assert all(kwargs["filters"] is bot_module.PRIVATE_ONLY_FILTER for _, kwargs in command_handlers)
        assert all("ChatType.PRIVATE" in repr(handler[0][0]) for handler in message_handlers)
        # Третий handler — JSON-документы для batch outreach
        assert "Document.FileExtension('json')" in repr(message_handlers[2][0][0])
        mock_pc.set_message_callback.assert_called_once()
        mock_pc.set_draft_callback.assert_called_once()
        fake_builder.concurrent_updates.assert_called_once_with(True)
        fake_app.run_polling.assert_called_once_with(drop_pending_updates=True)


# ====== Batch Cold Outreach (on_json_document) ======


def _make_json_document_update(mock_update, file_name="batch.json", file_size=512, file_id="doc-1"):
    """Прикрепляет к моку Update документ с заданными атрибутами."""
    document = MagicMock()
    document.file_id = file_id
    document.file_name = file_name
    document.file_size = file_size
    mock_update.message.document = document
    mock_update.message.text = None
    return document


def _patch_json_document_handler(payload_bytes: bytes, *, is_active: bool = True):
    """Патчит зависимости on_json_document. Возвращает контекст-менеджер с моками."""
    file_mock = AsyncMock()
    file_mock.download_as_bytearray = AsyncMock(return_value=bytearray(payload_bytes))

    pc_mock = MagicMock()
    pc_mock.is_active = MagicMock(return_value=is_active)
    pc_mock.resolve_target_chat = AsyncMock(
        return_value={
            "chat_id": 999,
            "first_name": "Jane",
            "last_name": None,
            "username": "jane",
            "bio": None,
        }
    )

    return {
        "file_mock": file_mock,
        "pc_mock": pc_mock,
        "patches": [
            patch("handlers.bot_handlers.ensure_effective_user", new_callable=AsyncMock,
                  return_value={"settings": {"style": "userlike", "tz_offset": 0}}),
            patch("handlers.bot_handlers.update_last_msg_at", new_callable=AsyncMock),
            patch("handlers.bot_handlers.pyrogram_client", pc_mock),
            patch("handlers.bot_handlers.get_system_message", new_callable=AsyncMock,
                  side_effect=lambda lang, key, **_: f"<{key}>"),
        ],
    }


class TestOnJsonDocument:
    """Тесты для on_json_document()."""

    @pytest.mark.asyncio
    async def test_rejects_when_not_connected(self, mock_update, mock_context):
        _make_json_document_update(mock_update)
        bundle = _patch_json_document_handler(b"[]", is_active=False)
        with bundle["patches"][0], bundle["patches"][1], bundle["patches"][2], bundle["patches"][3]:
            await on_json_document(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        # resolve_target_chat не должен вызываться, если пользователь не подключён
        bundle["pc_mock"].resolve_target_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_oversize_file(self, mock_update, mock_context):
        _make_json_document_update(mock_update, file_size=10 * 1024 * 1024)
        bundle = _patch_json_document_handler(b"[]")
        mock_context.bot.get_file = AsyncMock(return_value=bundle["file_mock"])

        with bundle["patches"][0], bundle["patches"][1], bundle["patches"][2], bundle["patches"][3]:
            await on_json_document(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        args, _ = mock_update.message.reply_text.call_args
        assert "batch_outreach_too_large" in args[0]
        bundle["pc_mock"].resolve_target_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_invalid_json(self, mock_update, mock_context):
        _make_json_document_update(mock_update)
        bundle = _patch_json_document_handler(b"{not json")
        mock_context.bot.get_file = AsyncMock(return_value=bundle["file_mock"])

        with bundle["patches"][0], bundle["patches"][1], bundle["patches"][2], bundle["patches"][3]:
            await on_json_document(mock_update, mock_context)

        args, _ = mock_update.message.reply_text.call_args
        assert "batch_outreach_invalid" in args[0]

    @pytest.mark.asyncio
    async def test_rejects_non_list_payload(self, mock_update, mock_context):
        _make_json_document_update(mock_update)
        bundle = _patch_json_document_handler(b'{"username": "@x"}')
        mock_context.bot.get_file = AsyncMock(return_value=bundle["file_mock"])

        with bundle["patches"][0], bundle["patches"][1], bundle["patches"][2], bundle["patches"][3]:
            await on_json_document(mock_update, mock_context)

        args, _ = mock_update.message.reply_text.call_args
        assert "batch_outreach_invalid" in args[0]

    @pytest.mark.asyncio
    async def test_rejects_too_many_items(self, mock_update, mock_context):
        from handlers.bot_handlers import BATCH_OUTREACH_MAX_ITEMS
        items = [{"username": f"@user{i:05d}"} for i in range(BATCH_OUTREACH_MAX_ITEMS + 1)]
        _make_json_document_update(mock_update)
        bundle = _patch_json_document_handler(__import__("json").dumps(items).encode())
        mock_context.bot.get_file = AsyncMock(return_value=bundle["file_mock"])

        with bundle["patches"][0], bundle["patches"][1], bundle["patches"][2], bundle["patches"][3]:
            await on_json_document(mock_update, mock_context)

        args, _ = mock_update.message.reply_text.call_args
        assert "batch_outreach_too_many_items" in args[0]
        bundle["pc_mock"].resolve_target_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_valid_batch(self, mock_update, mock_context):
        items = [
            {"username": "@johndoe", "style": "friend", "instruction": "say hi"},
            {"username": "t.me/janedoe", "prompt": "  short prompt  "},
        ]
        _make_json_document_update(mock_update)
        bundle = _patch_json_document_handler(__import__("json").dumps(items).encode())
        mock_context.bot.get_file = AsyncMock(return_value=bundle["file_mock"])
        status_msg = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=status_msg)

        with bundle["patches"][0], bundle["patches"][1], bundle["patches"][2], bundle["patches"][3], \
             patch("handlers.bot_handlers._process_batch_item", new_callable=AsyncMock, return_value=True) as mock_proc:
            await on_json_document(mock_update, mock_context)

        assert mock_proc.await_count == 2
        status_msg.edit_text.assert_called_once()
        edit_text_args, _ = status_msg.edit_text.call_args
        assert "batch_outreach_success" in edit_text_args[0]


class TestProcessBatchItem:
    """Тесты для _process_batch_item() — валидация полей одной записи."""

    @pytest.mark.asyncio
    async def test_rejects_invalid_username(self, mock_user):
        item = {"username": "no-at-sign"}  # дефис недопустим в TG username
        with patch("handlers.bot_handlers.pyrogram_client") as mock_pc:
            mock_pc.resolve_target_chat = AsyncMock()
            ok = await _process_batch_item(mock_user, None, {}, 0, "userlike", item)
        assert ok is False
        mock_pc.resolve_target_chat.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw_username", [
        "johndoe",
        "@johndoe",
        "t.me/johndoe",
        "https://t.me/johndoe",
    ])
    async def test_accepts_username_variants(self, mock_user, raw_username):
        item = {"username": raw_username}
        with patch("handlers.bot_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.bot_handlers.get_user", new_callable=AsyncMock, return_value={"settings": {}}), \
             patch("handlers.bot_handlers._execute_cold_outreach", new_callable=AsyncMock, return_value=True):
            mock_pc.resolve_target_chat = AsyncMock(return_value={"chat_id": 1, "first_name": "x"})
            ok = await _process_batch_item(mock_user, None, {}, 0, "userlike", item)
        assert ok is True
        mock_pc.resolve_target_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_when_target_not_found(self, mock_user):
        item = {"username": "@johndoe"}
        with patch("handlers.bot_handlers.pyrogram_client") as mock_pc:
            mock_pc.resolve_target_chat = AsyncMock(return_value=None)
            ok = await _process_batch_item(mock_user, None, {}, 0, "userlike", item)
        assert ok is False

    @pytest.mark.asyncio
    async def test_invalid_style_falls_back_to_global(self, mock_user):
        item = {"username": "@johndoe", "style": "friendly"}  # 'friendly' не валиден
        with patch("handlers.bot_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.bot_handlers.update_chat_style", new_callable=AsyncMock) as mock_set_style, \
             patch("handlers.bot_handlers.get_user", new_callable=AsyncMock, return_value={"settings": {}}), \
             patch("handlers.bot_handlers._execute_cold_outreach", new_callable=AsyncMock, return_value=True) as mock_exec:
            mock_pc.resolve_target_chat = AsyncMock(return_value={"chat_id": 1, "first_name": "x"})
            ok = await _process_batch_item(mock_user, None, {}, 0, "business", item)

        assert ok is True
        # Невалидный стиль НЕ должен сохраниться в БД
        mock_set_style.assert_not_called()
        # _execute_cold_outreach получает global_style = "business"
        called_args = mock_exec.call_args.args
        assert called_args[6] == "business"

    @pytest.mark.asyncio
    async def test_empty_prompt_clears_per_chat_prompt(self, mock_user):
        item = {"username": "@johndoe", "prompt": "   "}
        with patch("handlers.bot_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.bot_handlers.update_chat_prompt", new_callable=AsyncMock) as mock_set_prompt, \
             patch("handlers.bot_handlers.get_user", new_callable=AsyncMock, return_value={"settings": {}}), \
             patch("handlers.bot_handlers._execute_cold_outreach", new_callable=AsyncMock, return_value=True):
            mock_pc.resolve_target_chat = AsyncMock(return_value={"chat_id": 1, "first_name": "x"})
            await _process_batch_item(mock_user, None, {}, 0, "userlike", item)

        # Пустой промпт должен сброситься в None
        mock_set_prompt.assert_awaited_once()
        assert mock_set_prompt.call_args.args[2] is None

    @pytest.mark.asyncio
    async def test_non_string_instruction_is_coerced(self, mock_user):
        item = {"username": "@johndoe", "instruction": 42}
        with patch("handlers.bot_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.bot_handlers.get_user", new_callable=AsyncMock, return_value={"settings": {}}), \
             patch("handlers.bot_handlers._execute_cold_outreach", new_callable=AsyncMock, return_value=True) as mock_exec:
            mock_pc.resolve_target_chat = AsyncMock(return_value={"chat_id": 1, "first_name": "x"})
            ok = await _process_batch_item(mock_user, None, {}, 0, "userlike", item)

        assert ok is True
        # instruction приводится к "42"
        called_args = mock_exec.call_args.args
        assert called_args[4] == "42"

    @pytest.mark.asyncio
    async def test_invalid_instruction_type_falls_back_to_empty(self, mock_user):
        item = {"username": "@johndoe", "instruction": {"nested": "object"}}
        with patch("handlers.bot_handlers.pyrogram_client") as mock_pc, \
             patch("handlers.bot_handlers.get_user", new_callable=AsyncMock, return_value={"settings": {}}), \
             patch("handlers.bot_handlers._execute_cold_outreach", new_callable=AsyncMock, return_value=True) as mock_exec:
            mock_pc.resolve_target_chat = AsyncMock(return_value={"chat_id": 1, "first_name": "x"})
            await _process_batch_item(mock_user, None, {}, 0, "userlike", item)

        called_args = mock_exec.call_args.args
        assert called_args[4] == ""
