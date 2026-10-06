import numpy as np

from lisn.tts.base import Audio, WordTiming
from lisn.tts.cache import AudioCache


def test_roundtrip(tmp_path):
    cache = AudioCache(tmp_path)
    audio = Audio(np.arange(10, dtype=np.float32), 8000, (WordTiming("hi", 0.0, 0.5),))
    key = AudioCache.key("fake", "v", 1.0, "hi")
    assert cache.get(key) is None
    cache.put(key, audio)
    loaded = cache.get(key)
    assert loaded is not None
    assert loaded.sample_rate == 8000
    assert loaded.timings == audio.timings
    assert np.array_equal(loaded.samples, audio.samples)
    assert cache.size_bytes() > 0
    assert cache.clear() == 1
    assert cache.get(key) is None


def test_key_depends_on_all_inputs():
    base = AudioCache.key("e", "v", 1.0, "t")
    assert base != AudioCache.key("e2", "v", 1.0, "t")
    assert base != AudioCache.key("e", "v2", 1.0, "t")
    assert base != AudioCache.key("e", "v", 1.1, "t")
    assert base != AudioCache.key("e", "v", 1.0, "t2")


def test_corrupt_entry_is_dropped(tmp_path):
    cache = AudioCache(tmp_path)
    key = AudioCache.key("e", "v", 1.0, "t")
    path = cache.path_for(key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a npz")
    assert cache.get(key) is None
    assert not path.exists()
