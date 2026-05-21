import os
from pathlib import Path


PROTOTYPE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PROTOTYPE_DIR.parent

# Model files reused from existing project
MODEL_HOLISTIC_META = PROJECT_ROOT / "model" / "model_meta.json"
MODEL_HOLISTIC_WEIGHTS = PROJECT_ROOT / "model" / "model.pth"
MODEL_HANDS_META = PROJECT_ROOT / "model" / "model_hands_meta.json"
MODEL_HANDS_WEIGHTS = PROJECT_ROOT / "model" / "model_hands.pth"

PHRASES_FILE = PROTOTYPE_DIR / "data" / "phrases.json"
STATIC_DIR = PROTOTYPE_DIR / "app" / "static"

SEQUENCE_LENGTH = int(os.getenv("VOFALINK_SEQUENCE_LENGTH", "30"))
LETTER_THRESHOLD = float(os.getenv("VOFALINK_LETTER_THRESHOLD", "0.75"))
WORD_THRESHOLD = float(os.getenv("VOFALINK_WORD_THRESHOLD", "0.55"))
TOP2_MARGIN = float(os.getenv("VOFALINK_TOP2_MARGIN", "0.05"))
PHRASE_HISTORY_SIZE = int(os.getenv("VOFALINK_PHRASE_HISTORY_SIZE", "6"))
PHRASE_MIN_STABLE = int(os.getenv("VOFALINK_PHRASE_MIN_STABLE", "4"))

ASSEMBLER_HISTORY = int(os.getenv("VOFALINK_ASSEMBLER_HISTORY", "6"))
ASSEMBLER_MIN_STABLE = int(os.getenv("VOFALINK_ASSEMBLER_MIN_STABLE", "4"))
ASSEMBLER_COOLDOWN = float(os.getenv("VOFALINK_ASSEMBLER_COOLDOWN", "0.9"))
ASSEMBLER_WORD_TIMEOUT = float(os.getenv("VOFALINK_WORD_TIMEOUT", "2.0"))
