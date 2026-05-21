from prototype.app.services.assembler import LetterAssembler


def test_letter_assembly_and_commit():
    assembler = LetterAssembler(history_size=5, min_stable_count=3, cooldown_seconds=0.0, word_timeout_seconds=0.5)

    t = 0.0
    for _ in range(3):
        state = assembler.update("V", 0.95, now=t)
        t += 0.1
    for _ in range(3):
        state = assembler.update("O", 0.95, now=t)
        t += 0.1

    assert state.current_word == "VO"
    assert state.built_text == "VO"

    state = assembler.update(None, 0.0, now=t + 1.0)
    assert state.current_word == ""
    assert state.built_text == "VO"


def test_del_and_space():
    assembler = LetterAssembler(history_size=4, min_stable_count=2, cooldown_seconds=0.0, word_timeout_seconds=10.0)
    t = 0.0

    assembler.update("A", 0.99, now=t)
    assembler.update("A", 0.99, now=t + 0.1)
    assembler.update("DEL", 0.99, now=t + 0.2)
    state = assembler.update("SPACE", 0.99, now=t + 0.3)

    assert state.current_word == ""
    assert state.built_text == ""
