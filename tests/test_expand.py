import pytest

from lisn.text.expand import expand_text, expand_token


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("e.g.", "for example"),
        ("Dr.", "Doctor"),
        ("i.e.,", "that is,"),
        ("https://example.com/path?x=1", "link"),
        ("(www.example.com).", "link"),
        ("someone@example.org", "email address"),
        ("$5", "five dollars"),
        ("$1,500.50", "one thousand, five hundred dollars and fifty cents"),
        ("₹250", "two hundred and fifty rupees"),
        ("€1", "one euro"),
        ("$2k", "two thousand dollars"),
        ("45%", "forty five percent"),
        ("3rd", "third"),
        ("21st,", "twenty first,"),
        ("2024-03-05", "March fifth, twenty twenty four"),
        ("3:30", "three thirty"),
        ("9:05", "nine oh five"),
        ("12:00", "twelve o'clock"),
        ("10-20", "ten to twenty"),
        ("5km", "five kilometers"),
        ("16GB", "sixteen gigabytes"),
        ("1,000", "one thousand"),
        ("3.14", "three point one four"),
        ("-7", "minus seven"),
        ("1999", "nineteen ninety nine"),
        ("2007", "two thousand and seven"),
        ("(42)", "(forty two)"),
        ("hello", "hello"),
        ("Hello,", "Hello,"),
        ("—", ","),
        ("--", ","),
        ("*", ""),
        ("|", ""),
        ("...", "..."),
        ("/usr/local/bin", "file path"),
        ("A/B", "A/B"),
    ],
)
def test_expand_token(token: str, expected: str):
    assert expand_token(token) == expected


def test_expand_text_word_map_spans():
    result = expand_text("Pay $5 now.")
    assert result.speech_text == "Pay five dollars now."
    assert result.word_map == ((0, 1), (1, 3), (3, 4))


def test_expand_text_empty_span_for_dropped_token():
    result = expand_text("a * b")
    assert result.speech_text == "a b"
    assert result.word_map == ((0, 1), (1, 1), (1, 2))


def test_expand_text_dash_becomes_pause():
    assert expand_text("a — b").speech_text == "a , b"


def test_expand_text_rejects_non_str():
    with pytest.raises(TypeError):
        expand_text(None)  # type: ignore[arg-type]
