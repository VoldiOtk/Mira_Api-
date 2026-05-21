import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


NON_LETTER_TOKENS = {"SPACE", "DEL", "NOTHING", "BLANK"}


@dataclass
class AssemblerState:
    current_word: str
    built_text: str
    last_letter: str


class LetterAssembler:
    def __init__(
        self,
        history_size: int = 6,
        min_stable_count: int = 4,
        cooldown_seconds: float = 0.9,
        word_timeout_seconds: float = 2.0,
    ):
        self.history = deque(maxlen=history_size)
        self.min_stable_count = min_stable_count
        self.cooldown_seconds = cooldown_seconds
        self.word_timeout_seconds = word_timeout_seconds

        self.current_word_chars = []
        self.completed_words = []
        self.last_added_letter = ""
        self.last_added_ts = 0.0

    def _stable_letter(self) -> Optional[str]:
        if not self.history:
            return None
        candidate = max(set(self.history), key=self.history.count)
        if self.history.count(candidate) >= self.min_stable_count:
            return candidate
        return None

    def _commit_current_word(self) -> None:
        word = "".join(self.current_word_chars).strip()
        if word:
            self.completed_words.append(word)
        self.current_word_chars.clear()
        self.last_added_letter = ""

    def update(self, letter: Optional[str], confidence: float, now: Optional[float] = None) -> AssemblerState:
        now = now if now is not None else time.time()

        if letter and confidence > 0:
            norm_letter = letter.upper().strip()
            if norm_letter in NON_LETTER_TOKENS:
                if norm_letter == "DEL":
                    if self.current_word_chars:
                        self.current_word_chars.pop()
                elif norm_letter == "SPACE":
                    self._commit_current_word()
                self.history.clear()
            else:
                self.history.append(norm_letter)
                stable = self._stable_letter()
                can_add = (now - self.last_added_ts) >= self.cooldown_seconds
                if stable and stable != self.last_added_letter and can_add:
                    self.current_word_chars.append(stable)
                    self.last_added_letter = stable
                    self.last_added_ts = now
        else:
            if self.current_word_chars and (now - self.last_added_ts) >= self.word_timeout_seconds:
                self._commit_current_word()

        current_word = "".join(self.current_word_chars)
        built_text = " ".join(self.completed_words + ([current_word] if current_word else []))
        return AssemblerState(
            current_word=current_word,
            built_text=built_text,
            last_letter=self.last_added_letter,
        )

    def reset(self) -> None:
        self.history.clear()
        self.current_word_chars.clear()
        self.completed_words.clear()
        self.last_added_letter = ""
        self.last_added_ts = 0.0
