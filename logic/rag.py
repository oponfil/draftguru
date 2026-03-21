# logic/rag.py — Retrieval-Augmented Generation: поиск релевантных чанков документации

from clients.x402gate.openrouter_embeddings import get_embedding
from config import DEBUG_PRINT, RAG_SIMILARITY_THRESHOLD, RAG_TOP_K
from database.knowledge import match_knowledge_chunks
from utils.utils import get_timestamp


async def retrieve_context(question: str) -> str:
    """Ищет релевантные чанки документации для вопроса пользователя.

    Использует Supabase pgvector для similarity search по embeddings.

    Args:
        question: Текст вопроса пользователя

    Returns:
        Отформатированный текстовый блок с top-K чанками.
        Пустая строка, если ничего не найдено.
    """
    try:
        # 1. Получаем embedding вопроса
        query_embedding = await get_embedding(question)

        # 2. Ищем релевантные чанки
        chunks = await match_knowledge_chunks(
            query_embedding=query_embedding,
            match_count=RAG_TOP_K,
            match_threshold=RAG_SIMILARITY_THRESHOLD,
        )

        if not chunks:
            if DEBUG_PRINT:
                print(f"{get_timestamp()} [RAG] No relevant chunks found")
            return ""

        # 3. Форматируем найденные чанки
        formatted_parts = []
        for chunk in chunks:
            source = chunk.get("source", "?")
            section = chunk.get("section", "")
            similarity = chunk.get("similarity", 0)
            content = chunk.get("content", "")

            header = f"--- {source}"
            if section:
                header += f" | {section}"
            header += f" (relevance: {similarity:.2f}) ---"

            formatted_parts.append(f"{header}\n{content}")

        context = "\n\n".join(formatted_parts)

        if DEBUG_PRINT:
            print(
                f"{get_timestamp()} [RAG] Found {len(chunks)} chunk(s), "
                f"best similarity: {chunks[0].get('similarity', 0):.2f}"
            )

        return context

    except Exception as e:
        # RAG не должен ломать основной функционал бота
        print(f"{get_timestamp()} [RAG] ERROR: {e}")
        return ""
