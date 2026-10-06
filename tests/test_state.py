from lisn.player.state import StateStore, document_key
from lisn.text.pipeline import document_from_text


def test_save_and_resume(tmp_path, small_document):
    store = StateStore(tmp_path / "state.sqlite3")
    key = document_key(small_document)
    assert key.startswith("text:")
    assert store.resume_index(key, small_document) == 0
    store.save_position(key, small_document, 3, 50.0)
    assert store.resume_index(key, small_document) == 3
    saved = store.load_position(key)
    assert saved is not None and saved.sentence_id == small_document.sentences[3].id
    history = store.history()
    assert len(history) == 1 and history[0].title == "Doc"
    store.save_position(key, small_document, 5, 100.0)
    assert store.resume_index(key, small_document) == 0, "finished documents restart"
    store.forget(key)
    assert store.load_position(key) is None


def test_resume_by_id_survives_edits(tmp_path):
    store = StateStore(tmp_path / "s.db")
    original = document_from_text("Alpha one. Beta two. Gamma three.")
    store.save_position("k", original, 2, 60.0)
    edited = document_from_text("Inserted zero. Alpha one. Beta two. Gamma three.")
    assert store.resume_index("k", edited) == 3


def test_bookmarks(tmp_path, small_document):
    store = StateStore(tmp_path / "s.db")
    mark = store.add_bookmark("k", small_document, 1)
    assert mark.excerpt == "First sentence here."
    assert [b.id for b in store.bookmarks("k")] == [mark.id]
    assert store.bookmarks("other") == ()
    store.delete_bookmark(mark.id)
    assert store.bookmarks() == ()


def test_document_key_for_files_and_urls(tmp_path):
    from lisn.extract import extract
    from lisn.text.pipeline import build_document

    file = tmp_path / "a.txt"
    file.write_text("Hello there.")
    doc = build_document(extract(str(file)))
    assert document_key(doc).startswith("file:")
    from dataclasses import replace

    assert document_key(replace(doc, source="https://x.y/z")) == "https://x.y/z"
