# tests/test_rag.py — Тесты для RAG (embedding клиент, retrieval, интеграция, индексация)

from unittest.mock import AsyncMock, patch

import pytest


# ====== openrouter_embeddings ======


class TestGetEmbedding:
    """Тесты для get_embedding (одиночный)."""

    @pytest.mark.asyncio
    async def test_get_embedding_returns_vector(self):
        """get_embedding() возвращает embedding вектор."""
        fake_embedding = [0.1] * 1536

        with patch("clients.x402gate.openrouter_embeddings.x402gate_client") as mock_client:
            mock_client.available = True
            mock_client.request = AsyncMock(return_value={
                "data": {
                    "data": [{"embedding": fake_embedding, "index": 0}],
                },
            })

            from clients.x402gate.openrouter_embeddings import get_embedding
            result = await get_embedding("test text")

        assert result == fake_embedding
        assert len(result) == 1536

    @pytest.mark.asyncio
    async def test_get_embedding_unavailable_raises(self):
        """get_embedding() кидает ValueError, если x402gate не доступен."""
        with patch("clients.x402gate.openrouter_embeddings.x402gate_client") as mock_client:
            mock_client.available = False

            from clients.x402gate.openrouter_embeddings import get_embedding
            with pytest.raises(ValueError, match="EVM_PRIVATE_KEY"):
                await get_embedding("test")


class TestGetEmbeddings:
    """Тесты для get_embeddings (батч)."""

    @pytest.mark.asyncio
    async def test_get_embeddings_batch(self):
        """get_embeddings() обрабатывает батч из нескольких текстов."""
        emb1 = [0.1] * 1536
        emb2 = [0.2] * 1536

        with patch("clients.x402gate.openrouter_embeddings.x402gate_client") as mock_client:
            mock_client.available = True
            mock_client.request = AsyncMock(return_value={
                "data": {
                    "data": [
                        {"embedding": emb2, "index": 1},  # Порядок перемешан
                        {"embedding": emb1, "index": 0},
                    ],
                },
            })

            from clients.x402gate.openrouter_embeddings import get_embeddings
            result = await get_embeddings(["text1", "text2"])

        assert len(result) == 2
        # Проверяем, что результаты отсортированы по index
        assert result[0] == emb1
        assert result[1] == emb2

    @pytest.mark.asyncio
    async def test_get_embeddings_count_mismatch_raises(self):
        """get_embeddings() кидает RuntimeError при несовпадении количества."""
        with patch("clients.x402gate.openrouter_embeddings.x402gate_client") as mock_client:
            mock_client.available = True
            mock_client.request = AsyncMock(return_value={
                "data": {
                    "data": [{"embedding": [0.1] * 1536, "index": 0}],
                },
            })

            from clients.x402gate.openrouter_embeddings import get_embeddings
            with pytest.raises(RuntimeError, match="returned 1 embeddings for 2 inputs"):
                await get_embeddings(["text1", "text2"])

    @pytest.mark.asyncio
    async def test_get_embeddings_unexpected_response_raises(self):
        """get_embeddings() кидает RuntimeError при неожиданном ответе."""
        with patch("clients.x402gate.openrouter_embeddings.x402gate_client") as mock_client:
            mock_client.available = True
            mock_client.request = AsyncMock(return_value={"error": "bad request"})

            from clients.x402gate.openrouter_embeddings import get_embeddings
            with pytest.raises(RuntimeError, match="unexpected response"):
                await get_embeddings(["text"])


# ====== logic/rag.py ======


class TestRetrieveContext:
    """Тесты для retrieve_context."""

    @pytest.mark.asyncio
    async def test_retrieve_context_returns_formatted_chunks(self):
        """retrieve_context() возвращает отформатированные чанки."""
        fake_embedding = [0.1] * 1536
        fake_chunks = [
            {"id": 1, "source": "config.py", "section": "LLM_MODEL", "content": "LLM_MODEL = 'gemini'", "similarity": 0.85},
            {"id": 2, "source": "README.md", "section": "Settings", "content": "## Settings", "similarity": 0.72},
        ]

        with patch("logic.rag.get_embedding", new_callable=AsyncMock, return_value=fake_embedding), \
             patch("logic.rag.match_knowledge_chunks", new_callable=AsyncMock, return_value=fake_chunks):
            from logic.rag import retrieve_context
            result = await retrieve_context("what model?")

        assert "config.py" in result
        assert "LLM_MODEL" in result
        assert "README.md" in result
        assert "relevance: 0.85" in result

    @pytest.mark.asyncio
    async def test_retrieve_context_empty_when_no_chunks(self):
        """retrieve_context() возвращает пустую строку, если ничего не найдено."""
        with patch("logic.rag.get_embedding", new_callable=AsyncMock, return_value=[0.1] * 1536), \
             patch("logic.rag.match_knowledge_chunks", new_callable=AsyncMock, return_value=[]):
            from logic.rag import retrieve_context
            result = await retrieve_context("xxxxxxxxx")

        assert result == ""

    @pytest.mark.asyncio
    async def test_retrieve_context_error_returns_empty(self):
        """retrieve_context() не ломает бот при ошибках — возвращает пустую строку."""
        with patch("logic.rag.get_embedding", new_callable=AsyncMock, side_effect=RuntimeError("API down")):
            from logic.rag import retrieve_context
            result = await retrieve_context("test")

        assert result == ""


# ====== index_knowledge.py: чанкинг ======


class TestChunkPython:
    """Тесты для chunk_python — парсинг Python через AST."""

    def test_chunk_function(self, tmp_path):
        """Парсит функцию как отдельный чанк."""
        code = (
            "import os\n"
            "\n"
            "def hello():\n"
            '    """Say hello."""\n'
            '    print("hello")\n'
        )
        filepath = tmp_path / "test.py"
        filepath.write_text(code)

        with patch("scripts.index_knowledge.PROJECT_ROOT", str(tmp_path)):
            from scripts.index_knowledge import chunk_python
            chunks = chunk_python(str(filepath))

        # Должно быть 2 чанка: top-level (import) + функция
        sources = [c["section"] for c in chunks]
        assert "hello()" in sources
        assert "module-level" in sources

    def test_chunk_class_with_methods(self, tmp_path):
        """Парсит класс: заголовок + методы отдельно."""
        code = (
            "class MyClass:\n"
            '    """Docstring."""\n'
            "\n"
            "    def method_a(self):\n"
            "        pass\n"
            "\n"
            "    def method_b(self):\n"
            "        pass\n"
        )
        filepath = tmp_path / "test.py"
        filepath.write_text(code)

        with patch("scripts.index_knowledge.PROJECT_ROOT", str(tmp_path)):
            from scripts.index_knowledge import chunk_python
            chunks = chunk_python(str(filepath))

        sections = [c["section"] for c in chunks]
        assert "class MyClass" in sections
        assert "MyClass.method_a()" in sections
        assert "MyClass.method_b()" in sections

    def test_chunk_empty_file(self, tmp_path):
        """Пустой файл → 0 чанков."""
        filepath = tmp_path / "empty.py"
        filepath.write_text("")

        with patch("scripts.index_knowledge.PROJECT_ROOT", str(tmp_path)):
            from scripts.index_knowledge import chunk_python
            chunks = chunk_python(str(filepath))

        assert chunks == []


class TestChunkMarkdown:
    """Тесты для chunk_markdown — парсинг Markdown по заголовкам."""

    def test_chunk_by_headers(self, tmp_path):
        """Нарезает по H2/H3 заголовкам."""
        md = "# Title\n\nIntro\n\n## Section A\n\nContent A\n\n## Section B\n\nContent B\n"
        filepath = tmp_path / "test.md"
        filepath.write_text(md)

        with patch("scripts.index_knowledge.PROJECT_ROOT", str(tmp_path)):
            from scripts.index_knowledge import chunk_markdown
            chunks = chunk_markdown(str(filepath))

        sections = [c["section"] for c in chunks]
        assert "Title" in sections
        assert "Section A" in sections
        assert "Section B" in sections

    def test_chunk_empty_markdown(self, tmp_path):
        """Пустой .md → 0 чанков."""
        filepath = tmp_path / "empty.md"
        filepath.write_text("")

        with patch("scripts.index_knowledge.PROJECT_ROOT", str(tmp_path)):
            from scripts.index_knowledge import chunk_markdown
            chunks = chunk_markdown(str(filepath))

        assert chunks == []


class TestChunkSql:
    """Тесты для chunk_sql — SQL целиком."""

    def test_sql_whole_file(self, tmp_path):
        """SQL-файл = один чанк."""
        sql = "CREATE TABLE test (id INT);\n"
        filepath = tmp_path / "test.sql"
        filepath.write_text(sql)

        with patch("scripts.index_knowledge.PROJECT_ROOT", str(tmp_path)):
            from scripts.index_knowledge import chunk_sql
            chunks = chunk_sql(str(filepath))

        assert len(chunks) == 1
        assert "CREATE TABLE" in chunks[0]["content"]


# ====== Промпт ======


class TestPromptRagInstruction:
    """Проверяем, что RAG-инструкция присутствует в BOT_PROMPT."""

    def test_bot_prompt_has_rag_instruction(self):
        from prompts import BOT_PROMPT
        assert "RELEVANT DOCUMENTATION" in BOT_PROMPT


# ====== database/knowledge.py ======


class TestReplaceAllChunks:
    """Тесты для replace_all_chunks (TRUNCATE + INSERT)."""

    @pytest.mark.asyncio
    async def test_replace_all_chunks_calls_delete_and_insert(self):
        """replace_all_chunks() делает DELETE + INSERT."""
        from unittest.mock import MagicMock

        rows = [
            {"source": "config.py", "section": "LLM", "content": "LLM_MODEL = 'gemini'", "embedding": [0.1] * 10},
        ]

        # Supabase builder chain (table/delete/neq/insert/execute) — синхронный
        mock_table = MagicMock()

        async def fake_run_supabase(fn):
            return fn()

        with patch("database.knowledge.supabase") as mock_sb, \
             patch("database.knowledge.run_supabase", side_effect=fake_run_supabase):
            mock_sb.table.return_value = mock_table

            from database.knowledge import replace_all_chunks
            await replace_all_chunks(rows)

        # DELETE вызван 1 раз, INSERT вызван 1 раз (1 батч)
        mock_table.delete.assert_called_once()
        mock_table.insert.assert_called_once_with(rows)
