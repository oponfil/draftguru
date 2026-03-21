# clients/x402gate/openrouter_embeddings.py — Получение embeddings через OpenRouter (via x402gate.io)
#
# Эндпоинт: POST /v1/openrouter/embeddings
# Формат: стандартный OpenAI Embeddings API.

from clients.x402gate import x402gate_client
from config import DEBUG_PRINT, RAG_EMBEDDING_MODEL
from utils.utils import get_timestamp


async def get_embedding(text: str) -> list[float]:
    """Получает embedding для одного текста через OpenRouter.

    Args:
        text: Текст для эмбеддинга

    Returns:
        Вектор embedding (list[float], 1536 dims для text-embedding-3-small)

    Raises:
        ValueError: Если клиент x402gate не инициализирован
        RuntimeError: При ошибках API
    """
    result = await get_embeddings([text])
    return result[0]


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Получает embeddings для списка текстов батчем через OpenRouter.

    Args:
        texts: Список текстов (до 100 штук)

    Returns:
        Список векторов embedding в том же порядке

    Raises:
        ValueError: Если клиент x402gate не инициализирован
        RuntimeError: При ошибках API
    """
    if not x402gate_client.available:
        raise ValueError(
            "EVM_PRIVATE_KEY is not set. "
            "Please set it in .env to use x402gate.io for OpenRouter."
        )

    payload = {
        "model": RAG_EMBEDDING_MODEL,
        "input": texts,
    }

    if DEBUG_PRINT:
        print(f"{get_timestamp()} [EMBEDDINGS] Requesting {len(texts)} embedding(s)...")

    result = await x402gate_client.request("/v1/openrouter/embeddings", payload)

    # x402gate оборачивает ответ в {"data": {...}}
    if "data" in result and isinstance(result["data"], dict):
        result = result["data"]

    # Парсим Embeddings API ответ
    if "data" not in result or not isinstance(result["data"], list):
        raise RuntimeError(f"OpenRouter Embeddings API returned unexpected response: {str(result)[:300]}")

    # Сортируем по index для гарантии порядка
    embeddings_data = sorted(result["data"], key=lambda x: x["index"])
    embeddings = [item["embedding"] for item in embeddings_data]

    if len(embeddings) != len(texts):
        raise RuntimeError(
            f"OpenRouter Embeddings API returned {len(embeddings)} embeddings "
            f"for {len(texts)} inputs"
        )

    if DEBUG_PRINT:
        print(f"{get_timestamp()} [EMBEDDINGS] Got {len(embeddings)} embedding(s)")

    return embeddings
