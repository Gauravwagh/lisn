from lisn.text.pipeline import document_from_text
from lisn.tts.base import WordTiming
from lisn.tts.timing import display_word_timings, proportional_timings


def test_proportional_timings_cover_duration():
    timings = proportional_timings(("a", "bbb"), 1.0)
    assert timings[0].start == 0.0
    assert abs(timings[-1].end - 1.0) < 1e-9
    assert timings[1].end - timings[1].start > timings[0].end - timings[0].start


def test_display_timings_merge_expanded_spans():
    sentence = document_from_text("Pay $5 now.").sentences[0]
    speech = tuple(WordTiming(w, i * 0.1, (i + 1) * 0.1) for i, w in enumerate(sentence.speech_text.split()))
    mapped = display_word_timings(sentence, speech, 0.4)
    assert [t.word for t in mapped] == ["Pay", "$5", "now."]
    assert mapped[1].start == speech[1].start and mapped[1].end == speech[2].end


def test_display_timings_fallback_on_mismatch():
    sentence = document_from_text("one two three").sentences[0]
    mapped = display_word_timings(sentence, (WordTiming("x", 0, 1),), 3.0)
    assert len(mapped) == 3 and abs(mapped[-1].end - 3.0) < 1e-9
