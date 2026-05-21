import json
from pathlib import Path
from typing import Optional


class PhraseMapper:
    def __init__(self, phrases_file: Path):
        self.gesture_map = {}
        self.word_map = {}
        self._load(phrases_file)

    def _load(self, phrases_file: Path) -> None:
        if not phrases_file.exists():
            return
        data = json.loads(phrases_file.read_text(encoding="utf-8"))
        self.gesture_map = {k.lower(): v for k, v in data.get("gesture_map", {}).items()}
        self.word_map = {k.upper(): v for k, v in data.get("spelled_word_map", {}).items()}

    def phrase_from_gesture(self, gesture_label: Optional[str]) -> Optional[str]:
        if not gesture_label:
            return None
        return self.gesture_map.get(gesture_label.lower())

    def phrase_from_word(self, spelled_word: Optional[str]) -> Optional[str]:
        if not spelled_word:
            return None
        normalized = spelled_word.replace(" ", "").replace("'", "").upper()
        return self.word_map.get(normalized)
