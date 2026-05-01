# config.py — Константы и настройки DraftGuru

import os

from dotenv import load_dotenv

load_dotenv()


# ====== TELEGRAM ======
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    print("⚠️  WARNING: BOT_TOKEN не задан!")

# ====== PYROGRAM (Client API) ======
PYROGRAM_API_ID = int(os.getenv("PYROGRAM_API_ID", "0"))
PYROGRAM_API_HASH = os.getenv("PYROGRAM_API_HASH", "")
if not PYROGRAM_API_ID or not PYROGRAM_API_HASH:
    print("⚠️  WARNING: PYROGRAM_API_ID или PYROGRAM_API_HASH не заданы!")

# ====== ОТЛАДКА ======
DEBUG_PRINT = os.getenv("DEBUG_PRINT", "False").lower() in ("true", "1", "yes")
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "False").lower() in ("true", "1", "yes")

# ====== БАЗА ДАННЫХ (Supabase) ======
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  WARNING: SUPABASE_URL или SUPABASE_KEY не заданы!")
USER_CACHE_TTL = 3600  # In-memory кэш get_user(), секунды

# ====== ШИФРОВАНИЕ СЕССИЙ ======
SESSION_ENCRYPTION_KEY = os.getenv("SESSION_ENCRYPTION_KEY", "")
if not SESSION_ENCRYPTION_KEY:
    print("⚠️  WARNING: SESSION_ENCRYPTION_KEY не задан! Шифрование сессий недоступно.")

# ====== x402gate.io (оплата USDC на Base) ======
X402GATE_URL = "https://x402gate.io"
X402GATE_TIMEOUT = 120  # Таймаут запроса (секунды)
X402GATE_PREPAID_TOPUP_AMOUNT = 0.5  # Сумма пополнения prepaid ($)
X402GATE_PREPAID_MIN_BALANCE = 0.10  # Минимальный порог баланса ($)
EVM_WALLET_LOW_BALANCE_WARN = 10.0  # Порог предупреждения о низком балансе USDC на кошельке ($)
EVM_PRIVATE_KEY = os.getenv("EVM_PRIVATE_KEY", "")

# ====== ЯЗЫК ======
DEFAULT_LANGUAGE_CODE = "en"  # Язык по умолчанию (ISO 639-1)

# ====== МОДЕЛЬ ИИ ======
# Альтернативные модели для FREE/FALLBACK/PRO (для быстрого переключения вручную):
#   FREE/FALLBACK: google/gemini-3.1-flash-lite-preview, deepseek/deepseek-v4-flash
#   PRO: openai/gpt-5.4, google/gemini-3.1-pro-preview, anthropic/claude-opus-4.7,
#        z-ai/glm-5.1, deepseek/deepseek-v4-pro
FREE_LLM_MODEL = "deepseek/deepseek-v4-flash"  # FREE-модель (по умолчанию)
PHOTO_ANALYSIS_MODEL = "google/gemini-3.1-flash-lite-preview"  # Модель для распознавания фото
TRANSLATION_MODEL = "google/gemini-3.1-flash-lite-preview"  # Модель для перевода системных сообщений
FALLBACK_MODEL = "thedrummer/cydonia-24b-v4.1"  # Резервная модель без фильтров при отказах PRO-моделей
# PRO-модель для каждого стиля. Используется при pro_model=True.
STYLE_PRO_MODELS: dict[str, str] = {
    "userlike": "deepseek/deepseek-v4-pro",
    "friend": "openai/gpt-5.4",
    "romance": "anthropic/claude-opus-4.7",
    "seducer": "deepseek/deepseek-v4-pro",
    "business": "deepseek/deepseek-v4-pro",
    "sales": "deepseek/deepseek-v4-pro",
    "paranoid": "deepseek/deepseek-v4-pro",
}
# Модель для быстрой пост-модерации отказов (дешевая и быстрая)
MODERATION_MODEL = "qwen/qwen3.5-flash-02-23"
# Уровень reasoning для конкретных моделей (minimal/low/medium/high).
# Если модели нет в словаре — используется "medium" по умолчанию.
MODEL_REASONING_EFFORT: dict[str, str] = {
    "google/gemini-3.1-pro-preview": "low",
    "qwen/qwen3.5-flash-02-23": "low",
    "qwen/qwen3.6-plus": "low",
    "z-ai/glm-5.1": "high",
}

# ====== VISION / MEDIA ======
TELEGRAM_MAX_GET_FILE_SIZE = 20 * 1024 * 1024  # Ограничение на скачивание медиа (видео/фото) в RAM


# ====== RETRY ======
RETRY_ATTEMPTS = 2  # Количество повторных попыток
RETRY_DELAY = 2.0  # Базовая задержка (секунды)
RETRY_EXPONENTIAL_BASE = 2.0  # База экспоненциальной задержки

# ====== ЛОКАЛИЗАЦИЯ ======
SYSTEM_MESSAGE_TRANSLATION_TIMEOUT = 60
SYSTEM_MESSAGES_FALLBACK_TTL_SECONDS = 300.0

# ====== КОНТЕКСТ ======
MAX_CONTEXT_MESSAGES = 50  # Макс. кол-во сообщений из чата для контекста (черновики)
MAX_CONTEXT_CHARS = 5000  # Макс. суммарная длина текста в истории (символы)
AUTO_REPLY_MAX_CONTEXT_MESSAGES = 150  # Макс. кол-во сообщений для режима автоответа
AUTO_REPLY_MAX_CONTEXT_CHARS = 15000  # Макс. суммарная длина текста для автоответа

# ====== QR LOGIN ======
QR_LOGIN_TIMEOUT_SECONDS = 120  # Таймаут ожидания сканирования QR-кода (секунды)
QR_LOGIN_POLL_INTERVAL = 2  # Интервал проверки сканирования (секунды)

# ====== PHONE LOGIN ======
PHONE_CODE_TIMEOUT_SECONDS = 120  # Таймаут на ввод кода при phone-логине (секунды)

# ====== DRAFT INTERACTION ======
DRAFT_PROBE_DELAY = 2  # Секунды ожидания после пробы (draft_typing)
DRAFT_VERIFY_DELAY = 3  # Секунды до проверки доставки AI-черновика
POLL_MISSED_INTERVAL = 60  # Интервал проверки пропущенных сообщений (секунды)
POLL_MISSED_DIALOGS_LIMIT = 10  # Кол-во последних приватных чатов для проверки
MAX_REGENERATIONS = 10  # Максимальное количество перегенераций при подряд идущих входящих сообщениях
POKE_FOLLOW_UP_TIMEOUT = 43200  # /poke: таймаут follow-up (12 часов)
STARTUP_DIALOGS_WARMUP_LIMIT = 100  # Кол-во диалогов для прогрева кэша access_hash при запуске сессии

# ====== TELEGRAM BOT ======
BOT_READ_TIMEOUT = 30  # Таймаут чтения ответа от Telegram API (секунды)

# ====== НАСТРОЙКИ ======
USER_PROMPT_MAX_LENGTH = 600  # Макс. длина пользовательского промпта (символы)
CHAT_PROMPT_MAX_LENGTH = 300  # Макс. длина per-chat промпта (символы)
DEFAULT_PRO_MODEL = True  # По умолчанию PRO-модель включена

# ====== ГОЛОСОВЫЕ СООБЩЕНИЯ ======
VOICE_TRANSCRIPTION_TIMEOUT = 60  # Таймаут ожидания транскрипции (секунды)
VOICE_TRANSCRIPTION_DELAY = 1  # Пауза между последовательными транскрипциями (секунды)

# ====== СТИКЕРЫ ======
STICKER_FALLBACK_EMOJI = "□"  # Fallback для стикеров без привязанного эмодзи (U+25A1)

# ====== АВТООТВЕТ ======
# {секунды: ключ сообщения} — None = выключено (по умолчанию)
CHAT_IGNORED_SENTINEL = -1  # Sentinel: чат полностью игнорируется (нет черновиков и автоответа)
CHAT_AUTONOMOUS_SENTINEL = -2  # Sentinel: автономный режим (модель сама решает когда отправить)
AUTONOMOUS_FALLBACK_DELAY = 120  # Запасная задержка (в секундах), если модель в автономном режиме не вернула тег DELAY
AUTO_REPLY_OPTIONS: dict[int | None, str] = {
    None: "auto_reply_off",
    CHAT_IGNORED_SENTINEL: "auto_reply_ignore",
    CHAT_AUTONOMOUS_SENTINEL: "auto_reply_autonomous",
    60: "auto_reply_1m",
    900: "auto_reply_15m",
    57600: "auto_reply_16h",
}

# ====== FOLLOW-UP ======
# Автоматическая отправка follow-up сообщения, если собеседник не ответил
# {секунды: ключ сообщения} — None = выключено (по умолчанию)
FOLLOW_UP_OPTIONS: dict[int | None, str] = {
    None: "follow_up_off",
    21600: "follow_up_6h",      # 6 часов
    86400: "follow_up_24h",     # 24 часа
}

# Чаты, полностью игнорируемые ботом (не генерируются черновики и автоответы).
# Saved Messages (chat_id == user_id) исключается отдельно в коде.
IGNORED_CHAT_IDS: set[int] = {
    777000,  # Telegram service notifications
}
# ====== СТИЛЬ ОБЩЕНИЯ ======

# Маппинг emoji → стиль (единый источник правды для emoji↔style)
EMOJI_TO_STYLE: dict[str, str] = {
    "🦉": "userlike",
    "🍻": "friend",
    "💕": "romance",
    "💼": "business",
    "💰": "sales",
    "🕵️": "paranoid",
    "😈": "seducer",
}

# Стиль по умолчанию — первый в EMOJI_TO_STYLE
DEFAULT_STYLE: str = next(iter(EMOJI_TO_STYLE.values()))

# Обратный маппинг стиль → emoji
STYLE_TO_EMOJI: dict[str, str] = {v: k for k, v in EMOJI_TO_STYLE.items()}

# {значение: ключ сообщения}
def _style_msg_key(style: str) -> str:
    return f"settings_style_{style}"

# Отображаемое имя стиля (из ключа)
def style_display_name(style: str) -> str:
    return style.title()

STYLE_OPTIONS: dict[str, str] = {
    style: _style_msg_key(style) for style in EMOJI_TO_STYLE.values()
}

# Количество чатов в /styles для отображения
ACTIVE_CHATS_LIMIT = 16
CHATS_FETCH_LIMIT = ACTIVE_CHATS_LIMIT * 10  # Запрос с запасом: группы/каналы фильтруются

# ====== RAG ======
RAG_EMBEDDING_MODEL = "openai/text-embedding-3-small"  # 1536 dims
RAG_TOP_K = 5                  # Макс. кол-во чанков в контексте (реально может быть 0..5)
RAG_SIMILARITY_THRESHOLD = 0.1  # Мин. cosine similarity (0..1); чанки ниже порога отбрасываются
INDEX_BATCH_SIZE = 100            # Размер батча для embedding-запросов и INSERT в Supabase

# ====== DASHBOARD (веб-UI, автообновление страницы) ======
# Интервал опроса API в браузере (сек). Затем — окно в секундах, после чего polling
# останавливается до перезагрузки страницы.
DASHBOARD_REFRESH_INTERVAL_SEC = 5
DASHBOARD_AUTO_REFRESH_DURATION_SEC = 300

# ====== ЧАСОВОЙ ПОЯС ======
# 30 популярных UTC-смещений (часы); дробные: +3.5 Иран, +4.5 Афганистан,
# +5.5 Индия, +9.5 Центральная Австралия
TIMEZONE_OFFSETS: list[float] = [
    -12, -11, -10, -9, -8, -7, -6, -5, -4, -3, -2, -1,
    0, 1, 2, 3, 3.5, 4, 4.5, 5, 5.5,
    6, 7, 8, 9, 9.5, 10, 11, 12, 13,
]
