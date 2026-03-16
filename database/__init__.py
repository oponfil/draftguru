# database/__init__.py — Инициализация Supabase клиента

import asyncio
from collections.abc import Callable
from typing import TypeVar

from supabase import Client, create_client

from config import (
    DEBUG_PRINT,
    RETRY_ATTEMPTS,
    RETRY_DELAY,
    RETRY_EXPONENTIAL_BASE,
    SUPABASE_KEY,
    SUPABASE_URL,
)
from utils.utils import get_timestamp

T = TypeVar("T")


# Глобальный экземпляр Supabase клиента
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def _is_retriable_supabase_error(error: Exception) -> bool:
    """Определяет, стоит ли повторять временную ошибку Supabase."""
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return True

    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int) and status_code in {408, 425, 429, 500, 502, 503, 504}:
        return True

    message = str(error).lower()
    transient_markers = (
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "connection refused",
        "temporary failure",
        "temporarily unavailable",
        "service unavailable",
        "server disconnected",
        "too many requests",
        "rate limit",
        "broken pipe",
        "network is unreachable",
    )
    return any(marker in message for marker in transient_markers)


async def run_supabase(operation: Callable[[], T]) -> T:
    """Выполняет синхронную операцию Supabase в отдельном потоке с retry."""
    last_error: Exception | None = None

    for attempt in range(RETRY_ATTEMPTS + 1):
        try:
            return await asyncio.to_thread(operation)
        except Exception as error:
            last_error = error

            if not _is_retriable_supabase_error(error):
                raise

            if attempt >= RETRY_ATTEMPTS:
                print(f"{get_timestamp()} [DB] Failed after {RETRY_ATTEMPTS} retries: {error}")
                raise

            delay = RETRY_DELAY * (RETRY_EXPONENTIAL_BASE ** attempt)
            if DEBUG_PRINT:
                print(f"{get_timestamp()} [DB] Transient Supabase error: {error}")
                print(f"{get_timestamp()} [DB] Retry {attempt + 1}/{RETRY_ATTEMPTS} after {delay:.1f}s...")
            await asyncio.sleep(delay)

    if last_error is not None:
        raise last_error
    raise RuntimeError("Unexpected error in run_supabase")
