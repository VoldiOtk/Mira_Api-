import json
import sys
from collections import deque
from pathlib import Path
from typing import Optional, Tuple

import torch

from prototype.app import config


PROJECT_ROOT = config.PROJECT_ROOT
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from model.model import ASLLstmModel, HandSignModel  # noqa: E402
from utils.mediapipe_extractor import MediaPipeExtractor  # noqa: E402


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_load_state_dict(path: Path, device: torch.device):
    try:
        return torch.load(path, map_location=device, weights_only=True)
    except TypeError:
        return torch.load(path, map_location=device)


class SignRecognizer:
    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.sequence = deque(maxlen=config.SEQUENCE_LENGTH)
        self.hands_extractor = MediaPipeExtractor(mode="hands")
        self.holistic_extractor = MediaPipeExtractor(mode="holistic")

        self.hands_actions = _load_json(config.MODEL_HANDS_META).get("actions", [])
        self.word_actions = _load_json(config.MODEL_HOLISTIC_META).get("actions", [])

        self.hands_model = self._load_hands_model()
        self.word_model = self._load_word_model()

    def _load_hands_model(self) -> Optional[HandSignModel]:
        if not config.MODEL_HANDS_WEIGHTS.exists() or not self.hands_actions:
            return None
        model = HandSignModel(input_size=1662, num_classes=len(self.hands_actions)).to(self.device)
        model.load_state_dict(_safe_load_state_dict(config.MODEL_HANDS_WEIGHTS, self.device))
        model.eval()
        return model

    def _load_word_model(self) -> Optional[ASLLstmModel]:
        if not config.MODEL_HOLISTIC_WEIGHTS.exists() or not self.word_actions:
            return None
        model = ASLLstmModel(input_size=1662, num_classes=len(self.word_actions)).to(self.device)
        model.load_state_dict(_safe_load_state_dict(config.MODEL_HOLISTIC_WEIGHTS, self.device))
        model.eval()
        return model

    @staticmethod
    def _top2_margin(probabilities: torch.Tensor) -> float:
        top_values = torch.topk(probabilities, k=min(2, probabilities.shape[0])).values
        if top_values.shape[0] < 2:
            return float(top_values[0].item())
        return float((top_values[0] - top_values[1]).item())

    def predict_letter(self, frame) -> Tuple[Optional[str], float, str]:
        rendered, keypoints = self.hands_extractor.process_frame(frame)
        if self.hands_model is None:
            return None, 0.0, rendered

        with torch.no_grad():
            logits = self.hands_model(torch.tensor([keypoints], dtype=torch.float32).to(self.device))[0]
            probs = torch.softmax(logits, dim=0)
            idx = torch.argmax(logits).item()
            confidence = float(probs[idx].item())
            margin = self._top2_margin(probs)

        if idx >= len(self.hands_actions):
            return None, 0.0, rendered
        if confidence < config.LETTER_THRESHOLD or margin < config.TOP2_MARGIN:
            return None, confidence, rendered
        return self.hands_actions[idx], confidence, rendered

    def predict_word_gesture(self, frame) -> Tuple[Optional[str], float, float, str]:
        rendered, keypoints = self.holistic_extractor.process_frame(frame)
        self.sequence.append(keypoints)
        if self.word_model is None or len(self.sequence) < config.SEQUENCE_LENGTH:
            return None, 0.0, 0.0, rendered

        with torch.no_grad():
            logits = self.word_model(torch.tensor([list(self.sequence)], dtype=torch.float32).to(self.device))[0]
            probs = torch.softmax(logits, dim=0)
            idx = torch.argmax(logits).item()
            confidence = float(probs[idx].item())
            margin = self._top2_margin(probs)

        if idx >= len(self.word_actions):
            return None, 0.0, 0.0, rendered
        return self.word_actions[idx], confidence, margin, rendered

    def reset_sequence(self) -> None:
        self.sequence.clear()
