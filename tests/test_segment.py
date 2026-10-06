from lisn.text.segment import split_long, split_sentences


def test_abbreviations_do_not_split():
    sentences = split_sentences("Dr. Smith arrived at 5 p.m. yesterday. He left, e.g. quickly.")
    assert sentences == ("Dr. Smith arrived at 5 p.m. yesterday.", "He left, e.g. quickly.")


def test_decimals_and_questions():
    assert split_sentences("Pi is 3.14. Really? Yes!") == ("Pi is 3.14.", "Really?", "Yes!")


def test_newlines_inside_paragraph_are_joined():
    assert split_sentences("One line\nwraps here. Next.") == ("One line wraps here.", "Next.")


def test_empty_input():
    assert split_sentences("   \n ") == ()


def test_long_sentence_is_split_at_clause():
    long = ("word " * 40 + ", " + "more " * 40).strip()
    parts = split_long(long, max_chars=120)
    assert len(parts) >= 2
    assert all(len(p) <= 120 for p in parts)
    assert " ".join(parts).replace(" ,", ",") == long.replace(" ,", ",")


def test_long_sentence_without_clauses_splits_at_words():
    long = "w" * 10 + (" " + "w" * 10) * 30
    parts = split_long(long, max_chars=50)
    assert all(len(p) <= 50 for p in parts)
    assert " ".join(parts) == long
