from lisn.text.normalize import collapse_whitespace, normalize


def test_ligatures_and_smart_quotes():
    assert normalize("ﬁnal “quote” ‘it’s’") == "final \"quote\" 'it's'"


def test_whitespace_and_blank_lines():
    text = "a  \t b   \n\n\n\nc \n"
    assert normalize(text) == "a b\n\nc"


def test_removes_soft_hyphen_and_zero_width():
    assert normalize("re­cord​ ok﻿") == "record ok"


def test_ellipsis_and_nbsp():
    assert normalize("wait… now then") == "wait... now then"


def test_crlf_normalized():
    assert normalize("one\r\ntwo\rthree") == "one\ntwo\nthree"


def test_normalize_rejects_non_str():
    import pytest

    with pytest.raises(TypeError):
        normalize(b"bytes")  # type: ignore[arg-type]


def test_collapse_whitespace():
    assert collapse_whitespace("a \n b\t\tc") == "a b c"
