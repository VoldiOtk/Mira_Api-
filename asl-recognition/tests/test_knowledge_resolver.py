"""Tests for KnowledgeBaseResolver service."""
import json
import os
import tempfile
import pytest

from backend.services.knowledge_base_resolver import KnowledgeBaseResolver


MINIMAL_KB = {
    "hello": {
        "en": "Hello",
        "fr": "Bonjour",
        "sw": "Habari",
        "description": "A greeting",
        "intent": "greeting",
        "related_signs": ["hi", "bye"],
    },
    "water": {
        "en": "Water",
        "fr": "Eau",
        "sw": "Maji",
        "description": "Liquid water",
        "intent": "object",
        "related_signs": ["drink"],
    },
}


@pytest.fixture
def kb_path(tmp_path):
    p = tmp_path / "labels.json"
    p.write_text(json.dumps(MINIMAL_KB), encoding="utf-8")
    return str(p)


@pytest.fixture
def resolver(kb_path):
    return KnowledgeBaseResolver(labels_path=kb_path)


class TestResolveSign:
    def test_known_sign_found(self, resolver):
        result = resolver.resolve_signs(["hello"])
        assert result["coverage_ratio"] == 1.0
        detail = result["sign_details"]["hello"]
        assert detail["found_in_kb"] is True
        assert detail["translations"]["fr"] == "Bonjour"

    def test_unknown_sign_fallback(self, resolver):
        result = resolver.resolve_signs(["unknown_xyz"])
        detail = result["sign_details"]["unknown_xyz"]
        assert detail["found_in_kb"] is False
        assert "unknown_xyz" in result["missing_signs"]

    def test_coverage_ratio_partial(self, resolver):
        result = resolver.resolve_signs(["hello", "unknown_xyz"])
        assert result["coverage_ratio"] == pytest.approx(0.5)

    def test_coverage_ratio_full(self, resolver):
        result = resolver.resolve_signs(["hello", "water"])
        assert result["coverage_ratio"] == 1.0

    def test_empty_list(self, resolver):
        result = resolver.resolve_signs([])
        assert result["coverage_ratio"] == 0.0
        assert result["missing_signs"] == []

    def test_case_insensitive(self, resolver):
        result = resolver.resolve_signs(["HELLO"])
        detail = result["sign_details"]["HELLO"]
        assert detail["found_in_kb"] is True

    def test_literal_sequence(self, resolver):
        result = resolver.resolve_signs(["hello", "water"])
        assert result["literal_sequence"] == "hello water"

    def test_sign_details_include_intent(self, resolver):
        result = resolver.resolve_signs(["hello"])
        assert result["sign_details"]["hello"]["intent"] == "greeting"


class TestBuildLlmContext:
    def test_returns_string(self, resolver):
        ctx = resolver.build_llm_context(["hello"], lang="fr")
        assert isinstance(ctx, str)

    def test_contains_sign_label(self, resolver):
        ctx = resolver.build_llm_context(["hello"], lang="fr")
        assert "hello" in ctx.lower()

    def test_contains_target_language(self, resolver):
        ctx = resolver.build_llm_context(["hello"], lang="fr")
        assert "French" in ctx

    def test_contains_translation(self, resolver):
        ctx = resolver.build_llm_context(["hello"], lang="fr")
        assert "Bonjour" in ctx


class TestGetTranslation:
    def test_known_fr(self, resolver):
        assert resolver.get_translation("hello", "fr") == "Bonjour"

    def test_known_en(self, resolver):
        assert resolver.get_translation("hello", "en") == "Hello"

    def test_unknown_falls_back_to_label(self, resolver):
        assert resolver.get_translation("xyz_unknown", "fr") == "xyz_unknown"

    def test_case_insensitive(self, resolver):
        assert resolver.get_translation("WATER", "fr") == "Eau"


class TestAnalyzeKb:
    def test_total_labels_correct(self, resolver):
        stats = resolver.analyze_kb()
        assert stats["total_labels"] == 2

    def test_coverage_score_is_float(self, resolver):
        stats = resolver.analyze_kb()
        assert 0.0 <= stats["coverage_score"] <= 1.0

    def test_labels_with_description_count(self, resolver):
        stats = resolver.analyze_kb()
        assert stats["labels_with_description"] == 2

    def test_labels_with_intent_count(self, resolver):
        stats = resolver.analyze_kb()
        assert stats["labels_with_intent"] == 2
