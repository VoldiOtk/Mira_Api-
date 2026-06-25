"""Tests for LLM Provider abstraction (LocalFallbackTranslationProvider + get_llm_provider)."""
import os
import pytest
import asyncio

import pytest_asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────

def run(coro):
    """Run an async function in tests that aren't marked async."""
    return asyncio.get_event_loop().run_until_complete(coro)


KB_HELLO = {
    "sign_details": {
        "hello": {
            "label": "hello",
            "translations": {"en": "Hello", "fr": "Bonjour", "sw": "Habari"},
            "description": "A greeting",
            "intent": "greeting",
            "related_signs": [],
            "found_in_kb": True,
        }
    },
    "literal_sequence": "hello",
    "missing_signs": [],
    "coverage_ratio": 1.0,
}

KB_UNKNOWN = {
    "sign_details": {
        "xyz": {
            "label": "xyz",
            "translations": {},
            "description": "",
            "intent": "unknown",
            "related_signs": [],
            "found_in_kb": False,
        }
    },
    "literal_sequence": "xyz",
    "missing_signs": ["xyz"],
    "coverage_ratio": 0.0,
}


# ── LocalFallbackTranslationProvider ─────────────────────────────────────────

class TestLocalFallback:
    @pytest.fixture
    def provider(self):
        from utils.llm_provider import LocalFallbackTranslationProvider
        return LocalFallbackTranslationProvider()

    def test_returns_dict(self, provider):
        result = run(provider.translate_sequence(["hello"], KB_HELLO, lang="fr"))
        assert isinstance(result, dict)

    def test_required_keys_present(self, provider):
        result = run(provider.translate_sequence(["hello"], KB_HELLO, lang="fr"))
        for key in ("natural_translation", "literal_translation", "intent",
                    "confidence", "provider", "fallback", "raw_signs"):
            assert key in result, f"Missing key: {key}"

    def test_provider_is_local_fallback(self, provider):
        result = run(provider.translate_sequence(["hello"], KB_HELLO, lang="fr"))
        assert result["provider"] == "local_fallback"

    def test_fallback_is_true(self, provider):
        result = run(provider.translate_sequence(["hello"], KB_HELLO, lang="fr"))
        assert result["fallback"] is True

    def test_confidence_range(self, provider):
        result = run(provider.translate_sequence(["hello"], KB_HELLO, lang="fr"))
        assert 0.0 <= result["confidence"] <= 1.0

    def test_single_sign_higher_confidence(self, provider):
        r1 = run(provider.translate_sequence(["hello"], KB_HELLO, lang="fr"))
        r2 = run(provider.translate_sequence(["hello", "world"], KB_HELLO, lang="fr"))
        assert r1["confidence"] >= r2["confidence"]

    def test_raw_signs_preserved(self, provider):
        signs = ["hello", "water"]
        result = run(provider.translate_sequence(signs, KB_HELLO, lang="fr"))
        assert result["raw_signs"] == signs

    def test_greeting_intent_detected(self, provider):
        result = run(provider.translate_sequence(["hello"], KB_HELLO, lang="fr"))
        assert result["intent"] == "greeting"

    def test_request_intent_detected(self, provider):
        result = run(provider.translate_sequence(["help"], {}, lang="fr"))
        assert result["intent"] == "request_help"

    def test_empty_kb_context_as_dict(self, provider):
        result = run(provider.translate_sequence(["hello"], {}, lang="fr"))
        assert isinstance(result, dict)

    def test_string_kb_context_handled(self, provider):
        result = run(provider.translate_sequence(["hello"], "some context string", lang="fr"))
        assert isinstance(result, dict)

    def test_target_language_preserved(self, provider):
        result = run(provider.translate_sequence(["hello"], KB_HELLO, lang="en"))
        assert result["target_language"] == "en"


# ── get_llm_provider ──────────────────────────────────────────────────────────

class TestGetLlmProvider:
    def test_returns_provider_instance(self):
        from utils.llm_provider import get_llm_provider, LLMTranslationProvider
        p = get_llm_provider("local")
        assert isinstance(p, LLMTranslationProvider)

    def test_local_explicit(self):
        from utils.llm_provider import get_llm_provider, LocalFallbackTranslationProvider
        p = get_llm_provider("local")
        assert isinstance(p, LocalFallbackTranslationProvider)

    def test_disabled_env_returns_local(self, monkeypatch):
        monkeypatch.setenv("LLM_TRANSLATION_ENABLED", "false")
        # Re-import to pick up env change
        import importlib, utils.llm_provider as mod
        importlib.reload(mod)
        p = mod.get_llm_provider()
        assert isinstance(p, mod.LocalFallbackTranslationProvider)
        importlib.reload(mod)  # restore

    def test_unknown_provider_returns_local(self):
        from utils.llm_provider import get_llm_provider, LocalFallbackTranslationProvider
        p = get_llm_provider("unknown_provider_xyz")
        assert isinstance(p, LocalFallbackTranslationProvider)
