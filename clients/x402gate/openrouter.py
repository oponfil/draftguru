# clients/x402gate/openrouter.py — Генерация текста через OpenRouter (via x402gate.io)
#
# Эндпоинт: POST /v1/openrouter/chat/completions
# Формат: стандартный OpenAI Chat Completions API.

import asyncio
import json
import os
import time
from datetime import datetime
import copy

from clients.x402gate import NonRetriableRequestError, TopupError, x402gate_client
from config import (
    FALLBACK_MODEL,
    FREE_LLM_MODEL,
    DEBUG_PRINT,
    LOG_TO_FILE,
    RETRY_ATTEMPTS,
    RETRY_DELAY,
    RETRY_EXPONENTIAL_BASE,
)
from dashboard import stats as dash_stats
from prompts import BOT_PROMPT
from utils.utils import get_timestamp

LOG_DIR = "logs"


class ContentFilterError(RuntimeError):
    """Контентный фильтр модели. Ретрай бесполезен — тот же контент будет заблокирован."""
    pass


def _log_to_file(
    payload: dict, response_text: str, model: str, duration: float, usage: dict, reasoning_text: str = "",
) -> None:
    """Записывает полный запрос и ответ в отдельный лог-файл."""
    if not LOG_TO_FILE:
        return

    os.makedirs(LOG_DIR, exist_ok=True)

    request_data = copy.deepcopy(payload["messages"])
    
    # Truncate long base64 strings to save space in logs
    for msg in request_data:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                part_type = part.get("type")
                if part_type in ("image_url", "video_url") and part_type in part:
                    url_obj = part[part_type]
                    if isinstance(url_obj, dict) and "url" in url_obj:
                        url_str = url_obj["url"]
                        if "base64," in url_str:
                            prefix, b64_data = url_str.split("base64,", 1)
                            if len(b64_data) > 100:
                                url_obj["url"] = f"{prefix}base64,{b64_data[:100]}...[TRUNCATED]"

    entry = {
        "timestamp": get_timestamp(),
        "model": model,
        "duration_s": round(duration, 2),
        "usage": usage,
        "request": request_data,
        "response": response_text,
    }
    if reasoning_text:
        entry["reasoning"] = reasoning_text

    safe_model = model.split("/")[-1].replace(".", "_")
    filename = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + f"_{safe_model}.log"
    filepath = os.path.join(LOG_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, indent=2) + "\n")


async def generate_response(
    user_message: str | list[dict],
    model: str = FREE_LLM_MODEL,
    system_prompt: str | None = BOT_PROMPT,
    reasoning_effort: str = "medium",
    chat_history: list[dict] | None = None,
) -> str:
    """Генерирует ответ на сообщение пользователя через OpenRouter.

    Args:
        user_message: Текст сообщения пользователя
        model: Модель OpenRouter (по умолчанию FREE_LLM_MODEL из config)
        system_prompt: Системный промпт (None — без системного промпта)
        reasoning_effort: Уровень reasoning (minimal/low/medium/high)
        chat_history: Предыдущие сообщения [{"role": "user"/"assistant", "content": "..."}]

    Returns:
        Текстовый ответ модели

    Raises:
        ValueError: Если клиент x402gate не инициализирован
        RuntimeError: При ошибках API
    """
    if not x402gate_client.available:
        raise ValueError(
            "EVM_PRIVATE_KEY is not set. "
            "Please set it in .env to use x402gate.io for OpenRouter."
        )

    # Формируем messages в формате Chat Completions
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if chat_history:
        messages.extend(chat_history)
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": model,
        "messages": messages,
        "reasoning": {"effort": reasoning_effort},
        "reasoning_effort": reasoning_effort,
    }

    api_path = "/v1/openrouter/chat/completions"
    start_time = time.time()
    last_error = None
    current_model = model

    # Retry с экспоненциальной задержкой
    for attempt in range(RETRY_ATTEMPTS + 1):
        try:
            payload["model"] = current_model
            result = await x402gate_client.request(api_path, payload)

            # x402gate оборачивает ответ в {"data": {...}}
            if "data" in result and isinstance(result["data"], dict):
                result = result["data"]

            # Парсим Chat Completions ответ
            if "choices" not in result or len(result["choices"]) == 0:
                raise RuntimeError("OpenRouter API returned empty response (no choices)")

            choice = result["choices"][0]
            message_data = choice["message"]
            text = message_data.get("content", "")

            # Проверяем finish_reason ДО проверки пустого текста:
            # типичный content_filter ответ — пустой content + finish_reason=content_filter.
            # Если проверять пустоту первой, ContentFilterError никогда не сработает.
            finish_reason = choice.get("finish_reason", "")
            if finish_reason == "content_filter":
                raise ContentFilterError(
                    f"Content blocked by model safety filter (finish_reason={finish_reason})"
                )

            if not text or not text.strip():
                raise RuntimeError("OpenRouter API returned empty response content")

            # Reasoning content (если модель поддерживает)
            reasoning_text = message_data.get("reasoning_content") or message_data.get("reasoning") or ""

            # Логируем информацию о токенах
            usage = result.get("usage", {}) or {}
            input_tokens = usage.get("prompt_tokens", 0) or 0
            output_tokens = usage.get("completion_tokens", 0) or 0
            completion_details = usage.get("completion_tokens_details") or {}
            reasoning_tokens = completion_details.get("reasoning_tokens", 0) or 0
            duration = time.time() - start_time

            token_info = f"tokens: {input_tokens} → {output_tokens}"
            if reasoning_tokens:
                token_info += f" (reasoning: {reasoning_tokens})"

            print(
                f"{get_timestamp()} [OPENROUTER] {current_model} | "
                f"{duration:.2f}s | {token_info}"
            )

            dash_stats.record_llm_request(
                model=current_model,
                latency_s=duration,
                tokens_in=input_tokens,
                tokens_out=output_tokens,
                reasoning_tokens=reasoning_tokens,
            )

            _log_to_file(payload, text.strip(), current_model, duration, usage, reasoning_text)

            return text.strip()

        except Exception as e:
            last_error = e
            dash_stats.record_llm_error()

            # TopupError — ретрай бесполезен
            if isinstance(e, (TopupError, NonRetriableRequestError, ValueError)):
                print(f"{get_timestamp()} [OPENROUTER] Non-retriable error: {e}")
                break

            # ContentFilterError или пустой ответ — обычно означает фильтр. Меняем на fallback если возможно.
            is_filter_or_empty = isinstance(e, ContentFilterError) or (isinstance(e, RuntimeError) and "empty response" in str(e).lower())
            
            if is_filter_or_empty:
                if current_model != FALLBACK_MODEL:
                    print(f"{get_timestamp()} [OPENROUTER] Model {current_model} failed ({e}). Switching to fallback model {FALLBACK_MODEL}...")
                    current_model = FALLBACK_MODEL
                    continue
                else:
                    print(f"{get_timestamp()} [OPENROUTER] Fallback model {current_model} also failed — not retrying: {e}")
                    break

            if attempt < RETRY_ATTEMPTS:
                delay = RETRY_DELAY * (RETRY_EXPONENTIAL_BASE ** attempt)
                if DEBUG_PRINT:
                    print(f"{get_timestamp()} [OPENROUTER] Error: {e!r}")
                    print(f"{get_timestamp()} [OPENROUTER] Retry {attempt + 1}/{RETRY_ATTEMPTS} after {delay:.1f}s...")
                await asyncio.sleep(delay)
                continue
            else:
                print(f"{get_timestamp()} [OPENROUTER] Failed after {RETRY_ATTEMPTS} retries: {e!r}")
                break

    if last_error:
        raise last_error
    raise RuntimeError("Unexpected error in generate_response")
