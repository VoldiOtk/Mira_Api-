import asyncio
import os
import re
import subprocess

import httpx


class OllamaTranslator:
    def __init__(
        self,
        model_name="gemma4:e2b",
        base_url=None,
        generate_timeout=120.0,
    ):
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.url = f"{self.base_url}/api/generate"
        self.tags_url = f"{self.base_url}/api/tags"
        self.model_name = model_name
        self.generate_timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", generate_timeout))

    async def translate_asl(self, sign_sequence):
        """
        Envoie les signes bruts détectés par l'IA de vision pour qu'Ollama
        génère une phrase en français complètement fluide et naturelle.
        """
        prompt = f"""Tu es un traducteur expert ASL vers français conversationnel.
Transforme la séquence brute en exactement UNE phrase naturelle, courte (4 à 14 mots), sans commentaire.
Pas de liste, pas de JSON, pas d'explication.
Exemple: HELLO DRINK -> Bonjour, je veux boire.

Signes détectés: {sign_sequence}
Réponse finale:"""

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.url,
                    json=payload,
                    timeout=self.generate_timeout,
                )
                if response.status_code == 200:
                    data = response.json()
                    cleaned = self._clean_output(data.get("response", ""))
                    if cleaned:
                        return cleaned
                    return f"{sign_sequence} (réponse vide Ollama)"

                print(f"[Ollama] Erreur API {response.status_code}: {response.text[:300]}")
                if response.status_code == 404:
                    return (
                        f"{sign_sequence} (modèle '{self.model_name}' introuvable — "
                        f"lance: ollama pull {self.model_name})"
                    )
                return f"{sign_sequence} (erreur Ollama {response.status_code})"

        except httpx.TimeoutException:
            print(
                f"[Ollama] Timeout après {self.generate_timeout}s "
                f"(premier chargement Gemma peut être long)."
            )
            return (
                f"{sign_sequence} (Ollama trop lent — réessaie ou augmente "
                f"OLLAMA_TIMEOUT_SECONDS dans .env)"
            )
        except httpx.ConnectError as e:
            print(f"[Ollama] Connexion refusée : {e}")
            return f"{sign_sequence} (Ollama hors-ligne — lance l'app Ollama ou: ollama serve)"
        except Exception as e:
            print(f"[Ollama] Exception : {e}")
            return f"{sign_sequence} (Ollama hors-ligne)"

    @staticmethod
    def _clean_output(text):
        clean = (text or "").strip()
        if not clean:
            return "Je n'ai pas bien compris, peux-tu répéter ?"

        clean = re.sub(r"`{1,3}", "", clean).strip()
        lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
        selected = lines[-1] if lines else clean
        selected = re.sub(r"^[\-\*\d\.\)\s]+", "", selected).strip()

        sentence_match = re.search(r"([A-ZÀ-ÖØ-Þ].*?[.!?])", selected)
        if sentence_match:
            return sentence_match.group(1).strip()
        if selected and not selected.endswith((".", "!", "?")):
            selected += "."
        return selected

    async def _ping(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(self.tags_url, timeout=5.0)
                return res.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
            return False

    async def warmup(self) -> None:
        """Charge le modèle en mémoire pour éviter le timeout à la première phrase."""
        if not await self._ping():
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    self.url,
                    json={
                        "model": self.model_name,
                        "prompt": "Bonjour.",
                        "stream": False,
                    },
                    timeout=self.generate_timeout,
                )
            print(f"[Ollama] Warmup terminé pour {self.model_name}")
        except Exception as e:
            print(f"[Ollama] Warmup ignoré: {e}")

    async def check_and_start(self):
        """
        Vérifie si Ollama tourne. Sinon, tente de le démarrer.
        """
        print(f"\n[Ollama] Vérification sur {self.base_url} ...")

        for attempt in range(8):
            if await self._ping():
                print("[Ollama] Connecté.")
                print(f"[Ollama] Modèle: {self.model_name}")
                await self.warmup()
                return

            print("[Ollama] Hors-ligne. Tentative de démarrage...")
            try:
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                print("[Ollama] Exécutable introuvable. Installe: https://ollama.com")
                return
            await asyncio.sleep(4)

        print("[Ollama] Impossible de se connecter après plusieurs tentatives.")
