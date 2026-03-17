from prompts import build_bot_chat_prompt, build_draft_prompt, build_reply_prompt, BOT_PROMPT, HUMAN_STYLE_RULES


class TestBuildBotChatPrompt:
    def test_no_style_returns_base_prompt_with_human_rules(self):
        """Без стиля — возвращает базовый BOT_PROMPT и HUMAN_STYLE_RULES."""
        prompt = build_bot_chat_prompt()
        assert prompt.startswith(BOT_PROMPT)
        assert HUMAN_STYLE_RULES in prompt
        assert "COMMUNICATION STYLE:" not in prompt

    def test_style_appends_communication_style_and_human_rules(self):
        """Стиль paranoid добавляет блок COMMUNICATION STYLE и HUMAN_STYLE_RULES."""
        prompt = build_bot_chat_prompt(style="paranoid")
        assert "COMMUNICATION STYLE:" in prompt
        assert "Paranoid Guru" in prompt
        assert HUMAN_STYLE_RULES in prompt
        assert prompt.startswith(BOT_PROMPT)

    def test_custom_prompt_is_not_included(self):
        """Пользовательский промпт НЕ добавляется в промпт бота — только в драфты/ответы."""
        prompt = build_bot_chat_prompt(style="paranoid")
        assert "USER PROFILE & CUSTOM INSTRUCTIONS:" not in prompt


class TestBuildDraftPrompt:
    def test_userlike_without_history_does_not_reference_chat_history_style(self):
        prompt = build_draft_prompt(has_history=False, style=None)

        assert "The chat history is empty" in prompt
        assert "Since there is no chat history" in prompt
        assert "Mimic the user's writing style from the chat history" not in prompt
        assert "Write naturally and human-like" not in prompt

    def test_userlike_with_history_references_chat_history_style(self):
        prompt = build_draft_prompt(has_history=True, style=None)

        assert "You receive the recent chat history" in prompt
        assert "Mimic the user's writing style from the chat history" in prompt
        assert "Write naturally and human-like" not in prompt

    def test_paranoid_style_included_in_draft_prompt(self):
        """Стиль paranoid добавляет блок про безопасность."""
        prompt = build_draft_prompt(has_history=True, style="paranoid")

        assert "Paranoid Guru" in prompt
        assert "gatekeeper" in prompt
        assert "scam" in prompt


class TestBuildReplyPrompt:
    def test_paranoid_style_included_in_reply_prompt(self):
        """Стиль paranoid добавляет блок про безопасность."""
        prompt = build_reply_prompt(style="paranoid")

        assert "Paranoid Guru" in prompt
        assert "gatekeeper" in prompt
        assert "scam" in prompt

