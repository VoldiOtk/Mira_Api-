from __future__ import annotations

import os
from abc import ABC, abstractmethod

from dotenv import load_dotenv

load_dotenv()

_LLM_PROVIDER_NAME = os.getenv("LLM_PROVIDER", "gemini").lower()
_LLM_ENABLED = os.getenv("LLM_TRANSLATION_ENABLED", "true").lower() != "false"
_LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "10"))

_INTENT_GREETING = {"hello", "hi", "bonjour", "salut", "hey"}
_INTENT_REQUEST = {"help", "please", "want", "need", "assist"}
_INTENT_CONFIRM = {"yes", "no", "ok", "sure", "agree"}


def _detect_intent(signs: list[str]) -> str:
    lower = {s.lower() for s in signs}
    if lower & _INTENT_GREETING:
        return "greeting"
    if lower & _INTENT_REQUEST:
        return "request_help"
    if lower & _INTENT_CONFIRM:
        return "confirmation"
    return "statement"


class LLMTranslationProvider(ABC):
    @abstractmethod
    async def translate_sequence(
        self,
        signs: list[str],
        kb_context: dict,
        lang: str = "fr",
    ) -> dict:
        ...


class LocalFallbackTranslationProvider(LLMTranslationProvider):
    async def translate_sequence(
        self,
        signs: list[str],
        kb_context: dict,
        lang: str = "fr",
    ) -> dict:
        sign_details = kb_context.get("sign_details", {})

        literal_parts = []
        for sign in signs:
            detail = sign_details.get(sign, {})
            translations = detail.get("translations", [])
            if translations:
                literal_parts.append(translations[0])
            else:
                literal_parts.append(sign)
        literal_translation = " ".join(literal_parts)

        from utils.gemini_client import GeminiTranslator
        natural_translation = GeminiTranslator._local_fallback(" ".join(signs))

        confidence = 0.55 if len(signs) == 1 else 0.45
        intent = _detect_intent(signs)

        return {
            "natural_translation": natural_translation,
            "literal_translation": literal_translation,
            "intent": intent,
            "confidence": confidence,
            "reconstructed": False,
            "reasoning_summary": "Local rule-based fallback used; no external LLM called.",
            "suggested_missing_signs": [],
            "provider": "local_fallback",
            "fallback": True,
            "target_language": lang,
            "raw_signs": list(signs),
        }


class GeminiTranslationProvider(LLMTranslationProvider):
    def __init__(self):
        from utils.gemini_client import GeminiTranslator
        self._translator = GeminiTranslator()

    async def translate_sequence(
        self,
        signs: list[str],
        kb_context: dict,
        lang: str = "fr",
    ) -> dict:
        fell_back = False
        try:
            import asyncio
            core = await asyncio.wait_for(
                self._translator.translate_sequence_structured(signs, kb_context, lang),
                timeout=_LLM_TIMEOUT,
            )
            fell_back = core.get("confidence", 1.0) < 0.5 and not core.get("natural_translation", "").strip()
        except Exception as e:
            print(f"[GeminiTranslationProvider] Exception: {e}")
            local = LocalFallbackTranslationProvider()
            result = await local.translate_sequence(signs, kb_context, lang)
            result["provider"] = "gemini"
            result["fallback"] = True
            return result

        return {
            "natural_translation": core.get("natural_translation", ""),
            "literal_translation": core.get("literal_translation", " ".join(signs)),
            "intent": core.get("intent", "unknown"),
            "confidence": core.get("confidence", 0.75),
            "reconstructed": core.get("reconstructed", False),
            "reasoning_summary": core.get("reasoning_summary", ""),
            "suggested_missing_signs": core.get("suggested_missing_signs", []),
            "provider": "gemini",
            "fallback": fell_back,
            "target_language": lang,
            "raw_signs": list(signs),
        }


def get_llm_provider(provider_name: str = None) -> LLMTranslationProvider:
    if not _LLM_ENABLED:
        return LocalFallbackTranslationProvider()

    name = (provider_name or _LLM_PROVIDER_NAME).lower()

    if name == "local":
        return LocalFallbackTranslationProvider()

    if name == "gemini":
        from utils.gemini_client import API_KEY
        if not API_KEY:
            return LocalFallbackTranslationProvider()
        return GeminiTranslationProvider()

    return LocalFallbackTranslationProvider()
