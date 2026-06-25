import time
from collections import Counter
from typing import Dict, List, Optional, Tuple


class SignSequenceBuilder:
    def __init__(
        self,
        confidence_threshold: float = 0.65,
        stable_frames_required: int = 3,
        smooth_window: int = 5,
        duplicate_cooldown_ms: float = 1500.0,
        sequence_timeout_ms: float = 5000.0,
        max_sequence_length: int = 20,
    ):
        self.confidence_threshold = confidence_threshold
        self.stable_frames_required = stable_frames_required
        self.smooth_window = smooth_window
        self.duplicate_cooldown_ms = duplicate_cooldown_ms
        self.sequence_timeout_ms = sequence_timeout_ms
        self.max_sequence_length = max_sequence_length

        self._prediction_history: List[Tuple[str, float, float]] = []
        self._confirmed_sequence: List[Tuple[str, float, float]] = []
        self._last_confirmed_label: str = ""
        self._last_confirmed_ts: float = 0.0
        self._session_context: Dict = {
            "total_frames_seen": 0,
            "signs_confirmed": 0,
            "session_started_ts": time.time() * 1000,
        }

    def push_prediction(self, label: str, confidence: float) -> dict:
        now_ms = time.time() * 1000
        self._session_context["total_frames_seen"] += 1

        self._prediction_history.append((label, confidence, now_ms))
        if len(self._prediction_history) > self.smooth_window:
            self._prediction_history = self._prediction_history[-self.smooth_window:]

        all_labels = [e[0] for e in self._prediction_history]
        pending_counts = Counter(all_labels)
        pending_sign: Optional[str] = pending_counts.most_common(1)[0][0] if pending_counts else None
        pending_confidence = 0.0
        if pending_sign:
            relevant = [e[1] for e in self._prediction_history if e[0] == pending_sign]
            pending_confidence = sum(relevant) / len(relevant) if relevant else 0.0

        confident_labels = [e[0] for e in self._prediction_history if e[1] >= self.confidence_threshold]
        confident_counts = Counter(confident_labels)

        confirmed = False
        confirmed_sign: Optional[str] = None

        if confident_counts and len(self._prediction_history) >= self.smooth_window:
            best_label, best_count = confident_counts.most_common(1)[0]
            if best_count >= self.stable_frames_required:
                not_duplicate = best_label != self._last_confirmed_label
                cooldown_ok = (now_ms - self._last_confirmed_ts) >= self.duplicate_cooldown_ms
                if not_duplicate or cooldown_ok:
                    avg_conf = sum(
                        e[1] for e in self._prediction_history
                        if e[0] == best_label and e[1] >= self.confidence_threshold
                    ) / best_count
                    self._confirmed_sequence.append((best_label, avg_conf, now_ms))
                    if len(self._confirmed_sequence) > self.max_sequence_length:
                        self._confirmed_sequence.pop(0)
                    self._last_confirmed_label = best_label
                    self._last_confirmed_ts = now_ms
                    self._session_context["signs_confirmed"] += 1
                    self._prediction_history = []
                    confirmed = True
                    confirmed_sign = best_label

        return {
            "confirmed": confirmed,
            "confirmed_sign": confirmed_sign,
            "pending_sign": pending_sign,
            "pending_confidence": round(pending_confidence, 4),
            "sequence": [e[0] for e in self._confirmed_sequence],
            "sequence_length": len(self._confirmed_sequence),
        }

    def get_sequence(self) -> List[str]:
        return [e[0] for e in self._confirmed_sequence]

    def get_rich_sequence(self) -> List[dict]:
        return [
            {"label": e[0], "confidence": e[1], "timestamp_ms": e[2]}
            for e in self._confirmed_sequence
        ]

    def reset(self) -> None:
        self._prediction_history = []
        self._confirmed_sequence = []
        self._last_confirmed_label = ""
        self._last_confirmed_ts = 0.0

    def should_auto_finalize(self) -> bool:
        if not self._confirmed_sequence:
            return False
        now_ms = time.time() * 1000
        return (now_ms - self._last_confirmed_ts) > self.sequence_timeout_ms

    def get_context(self) -> dict:
        return dict(self._session_context)


_SEQUENCE_BUILDERS: Dict[str, SignSequenceBuilder] = {}


def get_or_create_builder(session_id: str, **kwargs) -> SignSequenceBuilder:
    if session_id not in _SEQUENCE_BUILDERS:
        _SEQUENCE_BUILDERS[session_id] = SignSequenceBuilder(**kwargs)
    return _SEQUENCE_BUILDERS[session_id]


def remove_builder(session_id: str) -> None:
    _SEQUENCE_BUILDERS.pop(session_id, None)
