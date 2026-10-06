"""Unit tests for Kokoro helpers that do not need the model."""

from dataclasses import dataclass

import pytest

from lisn.errors import EngineError
from lisn.tts.kokoro import KokoroEngine, _timings_from_tokens, validate_voice


@dataclass
class Tok:
    text: str
    whitespace: str
    start_ts: float | None = None
    end_ts: float | None = None


def test_tokens_grouped_by_whitespace():
    tokens = [
        Tok("Hello", "", 0.1, 0.4),
        Tok(",", " ", 0.4, 0.45),
        Tok("world", "", 0.5, 0.9),
        Tok("!", "", None, None),
    ]
    words = _timings_from_tokens(tokens, offset=1.0)
    assert [w.word for w in words] == ["Hello,", "world!"]
    assert words[0].start == pytest.approx(1.1) and words[0].end == pytest.approx(1.45)
    assert words[1].start == pytest.approx(1.5) and words[1].end == pytest.approx(1.9)


def test_untimed_group_inherits_previous_end():
    words = _timings_from_tokens([Tok("a", " ", 0.0, 0.2), Tok("-", " ", None, None)], offset=0.0)
    assert words[1].start == words[1].end == pytest.approx(0.2)


def test_empty_tokens():
    assert _timings_from_tokens([], 0.0) == ()


def test_validate_voice():
    validate_voice("af_heart")
    validate_voice("af_heart,am_michael")
    with pytest.raises(EngineError):
        validate_voice("nope")
    with pytest.raises(EngineError):
        validate_voice("")


def test_voices_metadata():
    voices = KokoroEngine().voices()
    ids = {v.id for v in voices}
    assert {"af_heart", "hf_alpha", "bm_george"} <= ids
    hindi = next(v for v in voices if v.id == "hf_alpha")
    assert hindi.language == "hi" and hindi.gender == "female"


def test_empty_text_rejected():
    with pytest.raises(EngineError):
        KokoroEngine().synthesize("  ", "af_heart")
