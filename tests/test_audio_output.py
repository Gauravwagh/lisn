import numpy as np

from lisn.player.audio import DeviceOutput, SilentOutput


def test_device_callback_without_stream():
    out = DeviceOutput(volume=0.5)
    out._sample_rate = 10
    out._clip = np.ones(25, dtype=np.float32)
    buffer = np.zeros((10, 1), dtype=np.float32)
    out._callback(buffer, 10, None, None)
    assert np.allclose(buffer[:, 0], 0.5)
    assert out.position() == 1.0 and not out.finished()
    out.pause()
    out._callback(buffer, 10, None, None)
    assert np.allclose(buffer, 0.0) and out.position() == 1.0
    out.resume()
    out._callback(buffer, 10, None, None)
    out._callback(buffer, 10, None, None)
    assert out.finished()
    assert np.allclose(buffer[5:, 0], 0.0)
    out.set_volume(5)
    assert out._volume == 2.0
    out.stop()
    assert out.finished() and out.position() == 0.0
    out.close()


def test_silent_output_timing():
    out = SilentOutput(time_scale=100.0)
    out.play(np.zeros(1000, dtype=np.float32), 1000, start_seconds=0.5)
    assert out.position() >= 0.5
    out.pause()
    frozen = out.position()
    out.resume()
    out.stop()
    assert out.finished() and frozen >= 0.5
    out.set_volume(0.3)
    assert out.volume == 0.3
    out.close()
