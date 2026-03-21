#!/usr/bin/env python3
"""scripts/index_knowledge.py — Индексация кодовой базы DraftGuru в Supabase pgvector.

Парсит исходники проекта (Python AST + Markdown), нарезает на чанки
по естественным границам (функции, классы, секции) и загружает embeddings
в таблицу knowledge_chunks.

Идемпотентный: при каждом запуске полностью пересоздаёт базу знаний
(TRUNCATE + INSERT).

Запуск:
    python scripts/index_knowledge.py
"""

import ast
import asyncio
import os
import re
import sys
import time


# Добавляем корень проекта в sys.path (скрипт запускается из scripts/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from clients.x402gate.openrouter_embeddings import get_embeddings  # noqa: E402 — import after sys.path
from config import INDEX_BATCH_SIZE  # noqa: E402 — import after sys.path
from database.knowledge import replace_all_chunks  # noqa: E402 — import after sys.path
from utils.utils import get_timestamp  # noqa: E402 — import after sys.path

# Директории и файлы для индексации (относительно PROJECT_ROOT)
INCLUDE_DIRS = [
    "handlers",
    "clients",
    "logic",
    "database",
    "utils",
    "dashboard",
]
INCLUDE_FILES = [
    "bot.py",
    "config.py",
    "prompts.py",
    "system_messages.py",
    "README.md",
    "schema.sql",
]

# Исключения
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache", "tests", "scripts"}
EXCLUDE_FILES = {"__init__.py"}  # Обычно содержат только импорты





# ────────────────────── Сбор файлов ──────────────────────


def collect_files() -> list[str]:
    """Собирает список файлов для индексации."""
    files: list[str] = []

    # Отдельные файлы из корня
    for f in INCLUDE_FILES:
        path = os.path.join(PROJECT_ROOT, f)
        if os.path.isfile(path):
            files.append(path)

    # Директории рекурсивно
    for d in INCLUDE_DIRS:
        dir_path = os.path.join(PROJECT_ROOT, d)
        if not os.path.isdir(dir_path):
            continue
        for root, dirs, filenames in os.walk(dir_path):
            # Пропускаем исключённые директории
            dirs[:] = [dd for dd in dirs if dd not in EXCLUDE_DIRS]
            for fn in filenames:
                if fn in EXCLUDE_FILES:
                    continue
                files.append(os.path.join(root, fn))

    return files


# ────────────────────── Чанкинг: Python ──────────────────────


def _get_source_lines(source: str, node: ast.AST) -> str:
    """Извлекает текст узла AST из исходного кода."""
    lines = source.splitlines()
    start = node.lineno - 1  # AST: 1-indexed
    end = node.end_lineno  # inclusive в AST
    return "\n".join(lines[start:end])


def chunk_python(filepath: str) -> list[dict]:
    """Нарезает Python-файл на чанки по функциям и классам (AST)."""
    rel_path = os.path.relpath(filepath, PROJECT_ROOT).replace("\\", "/")

    try:
        with open(filepath, encoding="utf-8") as f:
            source = f.read()
    except Exception:
        return []

    if not source.strip():
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Файл с синтаксической ошибкой — берём целиком
        return [{"source": rel_path, "section": None, "content": source}]

    chunks: list[dict] = []
    used_lines: set[int] = set()

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            section = f"{node.name}()"
            content = _get_source_lines(source, node)
            chunks.append({"source": rel_path, "section": section, "content": content})
            used_lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))

        elif isinstance(node, ast.ClassDef):
            # Класс: берем docstring и сигнатуру класса, затем каждый метод отдельно
            first_method_line = None

            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if first_method_line is None:
                        first_method_line = child.lineno
                    method_content = _get_source_lines(source, child)
                    section = f"{node.name}.{child.name}()"
                    chunks.append({"source": rel_path, "section": section, "content": method_content})
                    used_lines.update(range(child.lineno, (child.end_lineno or child.lineno) + 1))

            # Заголовок класса (до первого метода)
            if first_method_line is not None:
                lines = source.splitlines()
                header = "\n".join(lines[node.lineno - 1 : first_method_line - 1])
            else:
                header = _get_source_lines(source, node)

            if header.strip():
                chunks.append({"source": rel_path, "section": f"class {node.name}", "content": header})

            used_lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))

    # Top-level код (импорты, константы, переменные — всё что не функции/классы)
    lines = source.splitlines()
    top_level_lines = []
    for i, line in enumerate(lines, 1):
        if i not in used_lines:
            top_level_lines.append(line)

    top_level = "\n".join(top_level_lines).strip()
    if top_level:
        # Убираем лишние пустые строки
        top_level = re.sub(r"\n{3,}", "\n\n", top_level)
        chunks.append({"source": rel_path, "section": "module-level", "content": top_level})

    return chunks


# ────────────────────── Чанкинг: Markdown ──────────────────────


def chunk_markdown(filepath: str) -> list[dict]:
    """Нарезает Markdown-файл на чанки по H2/H3 заголовкам."""
    rel_path = os.path.relpath(filepath, PROJECT_ROOT).replace("\\", "/")

    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return []

    if not content.strip():
        return []

    chunks: list[dict] = []
    current_section = None
    current_lines: list[str] = []

    for line in content.splitlines():
        # Проверяем на заголовок H1/H2/H3
        header_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if header_match:
            # Сохраняем предыдущую секцию
            if current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    chunks.append({"source": rel_path, "section": current_section, "content": text})

            current_section = header_match.group(2).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Последняя секция
    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            chunks.append({"source": rel_path, "section": current_section, "content": text})

    return chunks


# ────────────────────── Чанкинг: SQL ──────────────────────


def chunk_sql(filepath: str) -> list[dict]:
    """Берет SQL-файл целиком как один чанк."""
    rel_path = os.path.relpath(filepath, PROJECT_ROOT).replace("\\", "/")

    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return []

    if not content.strip():
        return []

    return [{"source": rel_path, "section": None, "content": content.strip()}]


# ────────────────────── Главная логика ──────────────────────


def chunk_file(filepath: str) -> list[dict]:
    """Выбирает стратегию чанкинга по расширению файла."""
    if filepath.endswith(".py"):
        return chunk_python(filepath)
    elif filepath.endswith(".md"):
        return chunk_markdown(filepath)
    elif filepath.endswith(".sql"):
        return chunk_sql(filepath)
    else:
        return []


async def main() -> None:
    """Главная функция индексации."""
    start_time = time.time()

    # 1. Собираем файлы
    files = collect_files()
    print(f"{get_timestamp()} [INDEX] Found {len(files)} files to process")

    # 2. Нарезаем на чанки
    all_chunks: list[dict] = []
    for filepath in files:
        chunks = chunk_file(filepath)
        all_chunks.extend(chunks)

    print(f"{get_timestamp()} [INDEX] Created {len(all_chunks)} chunks")

    if not all_chunks:
        print(f"{get_timestamp()} [INDEX] No chunks to index, exiting")
        return

    # 3. Генерируем embeddings батчами
    texts = [c["content"] for c in all_chunks]
    all_embeddings: list[list[float]] = []

    batches = [texts[i:i + INDEX_BATCH_SIZE] for i in range(0, len(texts), INDEX_BATCH_SIZE)]
    print(f"{get_timestamp()} [INDEX] Generating embeddings ({len(batches)} batch(es))...")

    for i, batch in enumerate(batches):
        embeddings = await get_embeddings(batch)
        all_embeddings.extend(embeddings)
        if len(batches) > 1:
            print(f"{get_timestamp()} [INDEX]   Batch {i + 1}/{len(batches)}: {len(batch)} embeddings")

    # 4. Очищаем таблицу и загружаем новые данные
    print(f"{get_timestamp()} [INDEX] Uploading to Supabase...")

    rows = [
        {
            "source": chunk["source"],
            "section": chunk["section"],
            "content": chunk["content"],
            "embedding": embedding,
        }
        for chunk, embedding in zip(all_chunks, all_embeddings)
    ]

    await replace_all_chunks(rows)

    duration = time.time() - start_time
    print(f"{get_timestamp()} [INDEX] ✅ Done: {len(all_chunks)} chunks indexed in {duration:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
