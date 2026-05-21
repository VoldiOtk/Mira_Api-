from pathlib import Path

from prototype.app.services.phrase_mapper import PhraseMapper


def test_phrase_mapper_from_word():
    phrases = Path(__file__).resolve().parents[1] / "data" / "phrases.json"
    mapper = PhraseMapper(phrases)
    assert mapper.phrase_from_word("BONJOUR") == "Bonjour"
    assert mapper.phrase_from_word("comment ca va") == "Comment ca va ?"


def test_phrase_mapper_from_gesture():
    phrases = Path(__file__).resolve().parents[1] / "data" / "phrases.json"
    mapper = PhraseMapper(phrases)
    assert mapper.phrase_from_gesture("hello") == "Bonjour"
    assert mapper.phrase_from_gesture("unknown") is None
