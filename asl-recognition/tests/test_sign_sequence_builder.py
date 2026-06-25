"""Tests for SignSequenceBuilder service."""
import time
import pytest

from backend.services.sign_sequence_builder import (
    SignSequenceBuilder,
    get_or_create_builder,
    remove_builder,
)


def make_builder(**kwargs):
    """Create a builder with fast settings for testing."""
    defaults = dict(
        confidence_threshold=0.65,
        stable_frames_required=3,
        smooth_window=5,
        duplicate_cooldown_ms=100.0,
        sequence_timeout_ms=200.0,
        max_sequence_length=5,
    )
    defaults.update(kwargs)
    return SignSequenceBuilder(**defaults)


class TestPushPrediction:
    def test_not_confirmed_below_threshold(self):
        b = make_builder()
        result = b.push_prediction("hello", 0.40)
        assert result["confirmed"] is False
        assert result["confirmed_sign"] is None

    def test_not_confirmed_insufficient_frames(self):
        b = make_builder(stable_frames_required=3, smooth_window=5)
        for _ in range(2):
            result = b.push_prediction("hello", 0.80)
        assert result["confirmed"] is False

    def test_confirmed_after_stable_frames(self):
        b = make_builder(stable_frames_required=3, smooth_window=3)
        for _ in range(3):
            result = b.push_prediction("hello", 0.80)
        assert result["confirmed"] is True
        assert result["confirmed_sign"] == "hello"

    def test_sequence_grows_after_confirmation(self):
        b = make_builder(stable_frames_required=3, smooth_window=3, duplicate_cooldown_ms=0)
        for _ in range(3):
            b.push_prediction("hello", 0.90)
        for _ in range(3):
            b.push_prediction("world", 0.90)
        assert "hello" in b.get_sequence()
        assert "world" in b.get_sequence()

    def test_duplicate_prevented_within_cooldown(self):
        b = make_builder(stable_frames_required=3, smooth_window=3, duplicate_cooldown_ms=9999)
        for _ in range(3):
            b.push_prediction("hello", 0.90)
        first_seq_len = len(b.get_sequence())
        for _ in range(3):
            b.push_prediction("hello", 0.90)
        assert len(b.get_sequence()) == first_seq_len

    def test_pending_sign_reported(self):
        b = make_builder(stable_frames_required=5, smooth_window=3)
        b.push_prediction("water", 0.70)
        result = b.push_prediction("water", 0.70)
        assert result["pending_sign"] == "water"

    def test_max_sequence_length_enforced(self):
        b = make_builder(stable_frames_required=1, smooth_window=1, duplicate_cooldown_ms=0, max_sequence_length=3)
        for sign in ["A", "B", "C", "D", "E"]:
            b.push_prediction(sign, 0.90)
        assert len(b.get_sequence()) <= 3


class TestGetSequence:
    def test_empty_initially(self):
        b = make_builder()
        assert b.get_sequence() == []

    def test_returns_list_of_strings(self):
        b = make_builder(stable_frames_required=3, smooth_window=3)
        for _ in range(3):
            b.push_prediction("yes", 0.85)
        seq = b.get_sequence()
        assert isinstance(seq, list)
        assert all(isinstance(s, str) for s in seq)


class TestReset:
    def test_clears_sequence(self):
        b = make_builder(stable_frames_required=3, smooth_window=3)
        for _ in range(3):
            b.push_prediction("hello", 0.90)
        assert len(b.get_sequence()) == 1
        b.reset()
        assert b.get_sequence() == []

    def test_clears_prediction_history(self):
        b = make_builder()
        b.push_prediction("hello", 0.90)
        b.reset()
        result = b.push_prediction("hello", 0.50)
        assert result["confirmed"] is False


class TestShouldAutoFinalize:
    def test_false_when_empty(self):
        b = make_builder()
        assert b.should_auto_finalize() is False

    def test_true_after_timeout(self):
        b = make_builder(
            stable_frames_required=3,
            smooth_window=3,
            duplicate_cooldown_ms=0,
            sequence_timeout_ms=10,
        )
        for _ in range(3):
            b.push_prediction("hello", 0.90)
        time.sleep(0.05)
        assert b.should_auto_finalize() is True

    def test_false_before_timeout(self):
        b = make_builder(
            stable_frames_required=3,
            smooth_window=3,
            sequence_timeout_ms=999_000,
        )
        for _ in range(3):
            b.push_prediction("hello", 0.90)
        assert b.should_auto_finalize() is False


class TestGetRichSequence:
    def test_fields_present(self):
        b = make_builder(stable_frames_required=3, smooth_window=3)
        for _ in range(3):
            b.push_prediction("hello", 0.85)
        rich = b.get_rich_sequence()
        assert len(rich) == 1
        assert "label" in rich[0]
        assert "confidence" in rich[0]
        assert "timestamp_ms" in rich[0]


class TestSessionRegistry:
    def test_get_or_create_returns_same_instance(self):
        sid = "test-session-abc"
        b1 = get_or_create_builder(sid)
        b2 = get_or_create_builder(sid)
        assert b1 is b2
        remove_builder(sid)

    def test_remove_builder(self):
        sid = "test-session-xyz"
        get_or_create_builder(sid)
        remove_builder(sid)
        b_new = get_or_create_builder(sid)
        assert b_new.get_sequence() == []
        remove_builder(sid)
