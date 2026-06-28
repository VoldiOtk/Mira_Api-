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
        self.system_instruction_fr = (
            "Tu es un traducteur expert ASL vers français conversationnel. "
            "Sortie: exactement UNE phrase française naturelle et courte (4-14 mots). "
            "Pas de liste, pas de JSON, pas de commentaire."
        )
        self.system_instruction_en = (
            "You are an expert ASL to English conversational translator. "
            "Output: exactly ONE natural, short English sentence (4-14 words). "
            "No list, no JSON, no commentary."
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

    def _instruction_for_lang(self, lang):
        return self.system_instruction_en if lang == "en" else self.system_instruction_fr

    def _build_payload(self, sign_sequence, lang="fr"):
        lang = "en" if lang == "en" else "fr"
        user_hint = (
            f"Style: {CONVERSATION_STYLE}. Turn this ASL sequence into one conversational sentence: {sign_sequence}"
            if lang == "en"
            else f"Style: {CONVERSATION_STYLE}. Transforme cette sequence ASL en une phrase conversationnelle: {sign_sequence}"
        )
        return {
            "system_instruction": {
                "parts": [{"text": self._instruction_for_lang(lang)}]
            },
            "contents": [
                {
                    "parts": [{"text": user_hint}]
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
    def _local_fallback(sign_sequence, lang="fr"):
        tokens = [t.strip().lower() for t in sign_sequence.split() if t.strip()]
        if not tokens:
            return "I did not recognize a clear sign." if lang == "en" else "Je n'ai pas reconnu de signe clair."

        if lang == "en":
            mapping = {
                "hello": "hello",
                "hi": "hi",
                "thanks": "thanks",
                "thankyou": "thanks",
                "drink": "a drink",
                "eat": "food",
                "help": "help",
                "yes": "yes",
                "no": "no",
                "book": "a book",
                "go": "to go",
                "walk": "to walk",
                "family": "family",
                "want": "to want",
            }
            converted = [mapping.get(tok, tok) for tok in tokens]
            if "hello" in converted and len(converted) == 1:
                return "Hello!"
            if len(converted) == 1:
                return f"I want {converted[0]}."
            if "hello" in converted:
                tail = [w for w in converted if w != "hello"]
                if tail:
                    return f"Hello, I want {' '.join(tail)}."
                return "Hello!"
            return f"I want {' '.join(converted)}."

        mapping = {
            "hello": "salut",
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

        if "salut" in converted and len(converted) == 1:
            return "Salut !"
        if "bonjour" in converted and len(converted) == 1:
            return "Salut !"
        if len(converted) == 1 and converted[0] in {"oui", "non", "merci"}:
            return converted[0].capitalize() + "."
        if len(converted) == 1:
            return f"Je veux {converted[0]}."
        if len(converted) == 2 and converted[1] in {"boire", "manger", "de l'aide"}:
            return f"Je veux {converted[1]}."
        if "salut" in converted or "bonjour" in converted:
            tail = [w for w in converted if w not in {"salut", "bonjour"}]
            if tail:
                return f"Salut, je veux {' '.join(tail)}."
            return "Salut !"
        return f"Je veux {' '.join(converted)}."

    async def translate_asl(self, sign_sequence, lang="fr"):
        lang = "en" if lang == "en" else "fr"
        if not API_KEY:
            print("[Gemini] Erreur: Aucune clé API configurée dans le fichier .env")
            return f"{sign_sequence} (Clé manquante)"

        payload = self._build_payload(sign_sequence, lang=lang)

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
                return self._local_fallback(sign_sequence, lang=lang)
        except Exception as e:
            print(f" [Gemini Cloud] Exception globale : {e}")
            return self._local_fallback(sign_sequence, lang=lang)
