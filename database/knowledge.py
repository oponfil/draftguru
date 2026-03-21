# database/knowledge.py — Доступ к таблице knowledge_chunks (RAG)

from config import INDEX_BATCH_SIZE
from database import run_supabase, supabase


async def match_knowledge_chunks(
    query_embedding: list[float],
    match_count: int = 5,
    match_threshold: float = 0.3,
) -> list[dict]:
    """Ищет чанки документации по cosine similarity.

    Args:
        query_embedding: Вектор запроса (1536 dims)
        match_count: Макс. кол-во результатов
        match_threshold: Мин. cosine similarity (0..1)

    Returns:
        Список чанков с полями: id, source, section, content, similarity
    """
    result = await run_supabase(
        lambda: supabase.rpc(
            "match_knowledge_chunks",
            {
                "query_embedding": query_embedding,
                "match_count": match_count,
                "match_threshold": match_threshold,
            },
        ).execute()
    )
    return result.data if result.data else []


async def replace_all_chunks(rows: list[dict]) -> None:
    """Полностью заменяет содержимое knowledge_chunks (TRUNCATE + INSERT).

    Args:
        rows: Список dict с полями: source, section, content, embedding
    """
    # TRUNCATE (Supabase не поддерживает TRUNCATE напрямую)
    await run_supabase(
        lambda: supabase.table("knowledge_chunks").delete().neq("id", 0).execute()
    )

    # INSERT батчами
    for i in range(0, len(rows), INDEX_BATCH_SIZE):
        batch = rows[i:i + INDEX_BATCH_SIZE]
        await run_supabase(
            lambda b=batch: supabase.table("knowledge_chunks").insert(b).execute()
        )
