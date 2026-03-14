# Coding Style Guide & Conventions

Этот документ — **Style Guide** для проекта **TalkGuru**.
Описывает стандарты кодирования, обязательные для соблюдения.

## 1. Импорты (Imports)

### Основное правило
Все `import` и `from ... import ...` должны быть **в начале файла**.

### Запрет Lazy Imports
❌ Запрещено импортировать внутри функций.
✅ Исключение: разрыв циклических зависимостей (с комментарием `# circular dependency`).

### Порядок (PEP 8)
1. **Standard Library** (`os`, `sys`, `asyncio`, `typing`)
2. **Third Party** (`telegram`, `httpx`, `supabase`)
3. **Local Application** (`config`, `database`, `clients`)

## 2. Именование (Naming Conventions)

- **Классы**: `PascalCase` (`UserContext`)
- **Функции и переменные**: `snake_case` (`generate_response`)
- **Константы**: `UPPER_CASE` (`MAX_RETRIES`)
- **Приватные методы**: `_snake_case` (с префиксом `_`)

## 3. Форматирование и Стиль

- **Line Length**: 120 символов
- **Quotes**: Двойные кавычки `"` (стандарт Black)
- **Type Hinting**: Обязательно для всех функций (`def func(a: int) -> bool:`)
- **Docstrings**: На **русском языке**, обязательны для публичных функций

## 4. Асинхронность (Async/Await)

Все сетевые вызовы — `async`:
- Telegram API
- Supabase
- x402gate / OpenRouter

Для CPU-bound:
```python
result = await asyncio.to_thread(blocking_function, arg1)
```

## 5. Логирование

- Формат: `print(f"{get_timestamp()} [COMPONENT] Message")`
- ❌ Ошибки **не оборачивать** в `if DEBUG_PRINT:` — должны быть видны всегда
- ✅ Информационный вывод — `if DEBUG_PRINT:`
- Уровни: `[DEBUG]`, `[INFO]`, `[WARNING]`, `[ERROR]`

## 6. DRY (Don't Repeat Yourself)

❌ Не дублировать логику.
✅ Выносить общий код в отдельные функции.

## 7. Обратная Совместимость

❌ Не поддерживаем. Старый код удаляем сразу.
✅ Один формат, без fallback.

## 8. Linting (Ruff)

Используем **ruff** для проверки кода. Перед каждым коммитом:

```bash
ruff check .
```

- Все ошибки должны быть исправлены до коммита
- `# noqa: <RULE>` допустим только с обоснованием (например, `# noqa: E402` для намеренного порядка импортов)

## 9. Git Commits

### Формат: Conventional Commits
```
<type>(<scope>): <subject>

<body>
```

**Типы:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### Пример
```
feat(bot): add /start command with greeting message

- Register user in Supabase on first contact
- Send greeting with bot description
```

### PowerShell Workflow
```powershell
# Записать сообщение коммита в файл
[System.IO.File]::WriteAllText(".git-commit-msg.txt", "feat(scope): description")

# Закоммитить
git add -A
git commit -F .git-commit-msg.txt
```

## 10. Тестирование — TDD (Test-Driven Development)

Проект следует подходу **TDD** — разработка через тестирование.

### Принцип

1. 🔴 **Red** — Напиши тест на новую функциональность. Тест должен упасть.
2. 🟢 **Green** — Напиши минимальный код, чтобы тест прошёл.
3. 🔵 **Refactor** — Отрефактори код, не ломая тесты.

### Правила

- ❌ **Запрещено** мержить код без тестов
- ✅ Каждая новая функция / обработчик / утилита **обязана** иметь тесты
- ✅ Тесты покрывают **все модули** — без исключений
- ✅ Внешние зависимости **мокаются** — `.env` не нужен
- ✅ GitHub Actions автоматически запускает тесты при push и PR

### Запуск

```bash
pytest tests/ -v
```

Все тесты **должны** проходить перед каждым коммитом.

## 11. Code Review Checklist

1. [ ] **DRY**: Нет дублирования
2. [ ] **Imports**: В начале файла, без lazy imports
3. [ ] **Style**: Именование и типизация
4. [ ] **Async**: Сетевые вызовы через `await`
5. [ ] **Logging**: Ошибки без `if DEBUG_PRINT`
6. [ ] **Constants**: Всё в `config.py`
7. [ ] **Linting**: `ruff check .` проходит без ошибок
8. [ ] **Tests**: `pytest tests/ -v` проходит без ошибок
9. [ ] **Commits**: Conventional Commits, английский
