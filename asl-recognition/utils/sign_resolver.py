from __future__ import annotations


class FingerspellBuffer:
    def __init__(self):
        self.buffer = []

    def push(self, letter: str):
        self.buffer.append(letter)

    def flush(self) -> str:
        word = "".join(self.buffer)
        self.buffer.clear()
        return word

    def is_empty(self) -> bool:
        return len(self.buffer) == 0


def should_speak_instantly(label: str) -> bool:
    return False


def speech_text_for_label(label: str, lang: str = "fr") -> str:
    return label
