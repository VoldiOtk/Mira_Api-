from __future__ import annotations

import json
import os
import re
import httpx
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemma-4")
FALLBACK_MODELS = [
    model.strip() for model in os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemma-4,gemma-3-27b-it,gemini-2.0-flash,gemini-1.5-flash"
    ).split(",") if model.strip()
]
CONVERSATION_STYLE = os.getenv("AI_CONVERSATION_STYLE", "casual")

if not API_KEY:
    print(" [Alerte] Aucune clé API GEMINI_API_KEY trouvée dans le fichier .env !")

class GeminiTranslator:
    def __init__(self, model_name=DEFAULT_MODEL):
        self.model_name = self._normalize_model_name(model_name)
        self.fallback_models = [self.model_name] + [
            self._normalize_model_name(model)
            for model in FALLBACK_MODELS
            if self._normalize_model_name(model) != self.model_name
        ]
        self.system_instruction = (
            "Tu es un traducteur expert ASL vers français conversationnel. "
            "Entrée: suite de labels ASL bruts. "
            "Sortie: exactement UNE phrase française naturelle et courte (4-14 mots), "
            "comme une personne qui parle, pas une liste de mots ni une saisie clavier. "
            "Utilise de préférence des formulations conversationnelles comme "
            "'je veux...', 'j'ai besoin de...', 'bonjour...'. "
            "Interdictions: aucun commentaire, aucune puce, aucun JSON, aucun raisonnement, "
            "aucune citation de l'entrée brute. "
            "N'invente pas d'information non plausible."
        )

    @staticmethod
    def _normalize_model_name(model_name):
        normalized = model_name.strip()
        if normalized.startswith("models/"):
            normalized = normalized.split("/", 1)[1]
        return normalized

    def _build_url(self, model_name):
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent?key={API_KEY}"
        )

    def _build_payload(self, sign_sequence):
        return {
            "system_instruction": {
                "parts": [{"text": self.system_instruction}]
            },
            "contents": [
                {
                    "parts": [{
                        "text": (
                            f"Style: {CONVERSATION_STYLE}. "
                            f"Transforme cette séquence ASL brute en une phrase conversationnelle unique: "
                            f"{sign_sequence}"
                        )
                    }]
                }
            ],
            "generationConfig": {
                "temperature": 0.15,
                "topP": 0.9,
                "maxOutputTokens": 64
            }
        }

    @staticmethod
    def _extract_text(data):
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return GeminiTranslator._clean_output(text)
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def _clean_output(text):
        clean = (text or "").strip()
        if not clean:
            return ""

        clean = re.sub(r"`{1,3}", "", clean).strip()
        quote_matches = re.findall(r'"([^"]{3,})"', clean)
        if quote_matches:
            clean = quote_matches[-1].strip()

        lines = []
        for raw_line in clean.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^[\-\*\d\.\)\s]+", "", line).strip()
            if line.lower().startswith(("input:", "role:", "goal:", "constraint:")):
                continue
            lines.append(line)

        selected = clean if not lines else lines[-1].strip()
        sentence_match = re.search(r"([A-ZÀ-ÖØ-Þ].*?[.!?])", selected)
        if sentence_match:
            return sentence_match.group(1).strip()

        selected = selected.strip()
        if selected and not selected.endswith((".", "!", "?")):
            selected += "."
        return selected

    async def _translate_with_model(self, client, model_name, payload):
        url = self._build_url(model_name)
        response = await client.post(url, json=payload, timeout=12.0)
        if response.status_code == 200:
            text = self._extract_text(response.json())
            if text:
                self.model_name = model_name
                return text
            raise ValueError("Réponse vide du modèle.")
        print(
            f"[Gemini] Echec modèle {model_name} "
            f"(HTTP {response.status_code}): {response.text[:300]}"
        )
        return None

    @staticmethod
    def _local_fallback(sign_sequence):
        tokens = [t.strip().lower() for t in sign_sequence.split() if t.strip()]
        if not tokens:
            return "Je n'ai pas reconnu de signe clair."

        mapping = {
            "hello": "bonjour",
            "hi": "salut",
            "thanks": "merci",
            "thankyou": "merci",
            "please": "s'il te plaît",
            "drink": "boire",
            "water": "de l'eau",
            "eat": "manger",
            "help": "de l'aide",
            "yes": "oui",
            "no": "non",
            "book": "un livre",
            "go": "partir",
            "walk": "marcher",
            "family": "ma famille",
            "want": "vouloir",
        }
        converted = [mapping.get(tok, tok) for tok in tokens]

        if "bonjour" in converted and len(converted) == 1:
            return "Bonjour !"
        if len(converted) == 1 and converted[0] in {"oui", "non", "merci"}:
            return converted[0].capitalize() + "."
        if len(converted) == 1:
            return f"Je veux {converted[0]}."
        if len(converted) == 2 and converted[1] in {"boire", "manger", "de l'aide"}:
            return f"Je veux {converted[1]}."
        if "bonjour" in converted:
            tail = [w for w in converted if w != "bonjour"]
            if tail:
                return f"Bonjour, je veux {' '.join(tail)}."
            return "Bonjour !"
        return f"Je veux {' '.join(converted)}."

    def _build_structured_payload(self, signs: list, kb_context_str: str, lang: str) -> dict:
        lang_names = {"en": "English", "fr": "French", "sw": "Swahili"}
        lang_name = lang_names.get(lang, lang.capitalize())

        signs_arrow = " → ".join(signs)
        kb_block = kb_context_str if kb_context_str else "No KB context available."

        structured_system = (
            "You are an expert ASL (American Sign Language) interpreter and multilingual translator.\n"
            "You will receive a sequence of detected ASL signs and contextual information about each sign "
            "from a knowledge base.\n"
            "Your job is to reconstruct the speaker's intended natural message and translate it to the "
            "target language.\n"
            "IMPORTANT: Output ONLY valid JSON. No markdown, no explanation, no code blocks."
        )

        user_text = (
            f"Signs detected (in order): {signs_arrow}\n\n"
            f"Knowledge base context:\n{kb_block}\n\n"
            f"Target language: {lang_name}\n\n"
            f"Reconstruct the speaker's intended message. Output ONLY this JSON object:\n"
            "{{\n"
            f'  "natural_translation": "<natural sentence in {lang}>",\n'
            '  "literal_translation": "<word-for-word translation>",\n'
            '  "intent": "<greeting|request_help|statement|question|confirmation|action|unknown>",\n'
            '  "confidence": <0.0-1.0>,\n'
            '  "reconstructed": <true if gaps were filled>,\n'
            '  "reasoning_summary": "<one sentence>",\n'
            '  "suggested_missing_signs": []\n'
            "}}"
        )

        return {
            "system_instruction": {"parts": [{"text": structured_system}]},
            "contents": [{"parts": [{"text": user_text}]}],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.9,
                "maxOutputTokens": 256,
            },
        }

    @staticmethod
    def _extract_json(raw: str) -> dict | None:
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return None

    async def translate_sequence_structured(
        self,
        signs: list,
        kb_context: str = "",
        lang: str = "fr",
    ) -> dict:
        sign_sequence = " ".join(signs)
        payload = self._build_structured_payload(signs, kb_context, lang)

        parsed = None
        if API_KEY:
            try:
                async with httpx.AsyncClient() as client:
                    for model_name in self.fallback_models:
                        try:
                            url = self._build_url(model_name)
                            response = await client.post(url, json=payload, timeout=12.0)
                            if response.status_code == 200:
                                raw_text = self._extract_text(response.json())
                                parsed = self._extract_json(raw_text)
                                if parsed:
                                    self.model_name = model_name
                                    break
                        except Exception as e:
                            print(f"[Gemini structured] Erreur modèle ({model_name}): {e}")
            except Exception as e:
                print(f"[Gemini structured] Exception globale: {e}")

        if parsed:
            return {
                "natural_translation": str(parsed.get("natural_translation", "")),
                "literal_translation": str(parsed.get("literal_translation", sign_sequence)),
                "intent": str(parsed.get("intent", "unknown")),
                "confidence": float(parsed.get("confidence", 0.75)),
                "reconstructed": bool(parsed.get("reconstructed", True)),
                "reasoning_summary": str(parsed.get("reasoning_summary", "")),
                "suggested_missing_signs": list(parsed.get("suggested_missing_signs", [])),
            }

        natural = self._local_fallback(sign_sequence)
        return {
            "natural_translation": natural,
            "literal_translation": sign_sequence,
            "intent": "unknown",
            "confidence": 0.45,
            "reconstructed": False,
            "reasoning_summary": "Gemini unavailable; used local fallback.",
            "suggested_missing_signs": [],
        }

    async def translate_asl(self, sign_sequence):
        if not API_KEY:
            print("[Gemini] Erreur: Aucune clé API configurée dans le fichier .env")
            return f"{sign_sequence} (Clé manquante)"

        payload = self._build_payload(sign_sequence)

        try:
            async with httpx.AsyncClient() as client:
                for model_name in self.fallback_models:
                    try:
                        translated = await self._translate_with_model(client, model_name, payload)
                        if translated:
                            return translated
                    except httpx.HTTPError as e:
                        print(f"[Gemini] HTTP erreur ({model_name}) : {e}")
                    except Exception as e:
                        print(f"[Gemini] Erreur modèle ({model_name}) : {e}")
                print("[Gemini] Aucun modèle n'a pu traiter la requête.")
                return self._local_fallback(sign_sequence)
        except Exception as e:
            print(f" [Gemini Cloud] Exception globale : {e}")
            return self._local_fallback(sign_sequence)
