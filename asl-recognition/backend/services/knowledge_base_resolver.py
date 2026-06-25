"""
KnowledgeBaseResolver — enriches ASL sign labels for LLM context.
Supports both old format {en, fr, sw} and extended format with
description, intent, and related_signs fields.
"""

import json
import os
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_LABELS_PATH = os.path.join(BASE_DIR, "data", "knowledge", "labels.json")

LANG_NAMES = {
    "en": "English",
    "fr": "French",
    "sw": "Swahili",
}


class KnowledgeBaseResolver:
    """Resolves and enriches ASL sign labels from the knowledge base."""

    def __init__(self, labels_path: str = None):
        path = labels_path or DEFAULT_LABELS_PATH
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Normalise every entry to the extended format
        self._kb: Dict[str, dict] = {}
        for label, data in raw.items():
            self._kb[label.lower()] = {
                "en": data.get("en", label),
                "fr": data.get("fr", label),
                "sw": data.get("sw", label),
                "description": data.get("description", ""),
                "intent": data.get("intent", "unknown"),
                "related_signs": data.get("related_signs", []),
            }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_signs(self, signs: List[str]) -> dict:
        """Return enriched details for each sign plus summary statistics."""
        sign_details: Dict[str, dict] = {}
        missing: List[str] = []

        for raw_sign in signs:
            key = raw_sign.lower()
            entry = self._kb.get(key)
            if entry:
                sign_details[raw_sign] = {
                    "label": raw_sign,
                    "translations": {
                        "en": entry["en"],
                        "fr": entry["fr"],
                        "sw": entry["sw"],
                    },
                    "description": entry["description"],
                    "intent": entry["intent"],
                    "related_signs": entry["related_signs"],
                    "found_in_kb": True,
                }
            else:
                missing.append(raw_sign)
                sign_details[raw_sign] = {
                    "label": raw_sign,
                    "translations": {
                        "en": raw_sign,
                        "fr": raw_sign,
                        "sw": raw_sign,
                    },
                    "description": "",
                    "intent": "unknown",
                    "related_signs": [],
                    "found_in_kb": False,
                }

        total = len(signs)
        found = total - len(missing)
        coverage = found / total if total > 0 else 0.0

        return {
            "sign_details": sign_details,
            "literal_sequence": " ".join(signs),
            "missing_signs": missing,
            "coverage_ratio": coverage,
        }

    def build_llm_context(self, signs: List[str], lang: str = "fr") -> str:
        """Build a compact text block suitable for inclusion in an LLM prompt."""
        resolved = self.resolve_signs(signs)
        lines = ["Signs detected: " + ", ".join(signs), "Context:"]

        for raw_sign in signs:
            detail = resolved["sign_details"][raw_sign]
            translation = detail["translations"].get(lang, raw_sign)
            description = detail["description"]
            related = detail["related_signs"]

            line = "- {} ({})".format(raw_sign, translation)
            if description:
                line += ": " + description.rstrip(".")
            if related:
                line += ". Related: " + ", ".join(related)
            lines.append(line)

        lang_name = LANG_NAMES.get(lang, lang.capitalize())
        lines.append("Target language: " + lang_name)
        return "\n".join(lines)

    def get_translation(self, label: str, lang: str = "fr") -> str:
        """Return a single label's translation, falling back to the label itself."""
        entry = self._kb.get(label.lower())
        if entry:
            return entry.get(lang, label)
        return label

    def analyze_kb(self) -> dict:
        """Return quality statistics about the knowledge base."""
        total = len(self._kb)
        with_description = sum(1 for e in self._kb.values() if e["description"])
        with_intent = sum(
            1 for e in self._kb.values() if e["intent"] and e["intent"] != "unknown"
        )
        missing_french = [
            label
            for label, e in self._kb.items()
            if e["fr"].lower() == e["en"].lower()
        ]

        desc_score = with_description / total if total > 0 else 0.0
        intent_score = with_intent / total if total > 0 else 0.0
        french_score = (total - len(missing_french)) / total if total > 0 else 0.0
        coverage_score = (desc_score + intent_score + french_score) / 3.0

        return {
            "total_labels": total,
            "labels_with_description": with_description,
            "labels_with_intent": with_intent,
            "missing_french": missing_french,
            "coverage_score": round(coverage_score, 4),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_resolver: Optional[KnowledgeBaseResolver] = None


def get_knowledge_resolver() -> KnowledgeBaseResolver:
    """Return (and lazily create) the module-level singleton resolver."""
    global _resolver
    if _resolver is None:
        _resolver = KnowledgeBaseResolver()
    return _resolver
