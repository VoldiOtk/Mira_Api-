from __future__ import annotations
from typing import Any, Dict, List, Optional


class TextToSignService:
    def lookup(self, text: str, lang: str = "fr") -> Dict[str, Any]:
        return {"query": text, "lang": lang, "signs": [], "found": 0, "missing": [text], "message": "Service non configure"}

    def search(self, q: str, lang: str = "fr", limit: int = 25) -> List[Dict]:
        return []

    def vocabulary_stats(self) -> Dict[str, int]:
        return {"total": 0, "with_video": 0, "with_image": 0}

    def list_suggestions(self, lang: str = "fr", limit: int = 16) -> List[str]:
        return []

    async def convert(self, text: str, lang: str = "fr") -> Optional[str]:
        return None


text_to_sign_service = TextToSignService()
