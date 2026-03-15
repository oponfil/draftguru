# database/__init__.py — Инициализация Supabase клиента

import asyncio
from collections.abc import Callable
from typing import TypeVar

from supabase import Client, create_client

from config import SUPABASE_KEY, SUPABASE_URL

T = TypeVar("T")


# Глобальный экземпляр Supabase клиента
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


async def run_supabase(operation: Callable[[], T]) -> T:
    """Выполняет синхронную операцию Supabase в отдельном потоке."""
    return await asyncio.to_thread(operation)
