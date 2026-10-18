"""Shared scanner: fake camera / fake frames, no hardware."""
import queue
import time

import numpy as np
import pytest

from services import scanner as sc


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAMPION_CONFIG_DIR", str(tmp_path))
    return tmp_path


FRAME = np.zeros((48, 64, 3), dtype=np.uint8)


class FakeCamera:
    def __init__(self, opens=True, frames=None, released=None):
        self._opens, self._frames, self.released = opens, list(frames) if frames is not None else None, released if released is not None else []

    def open(self):
        return self._opens

    def read(self):
        if self._frames is None:
            return True, FRAME
        if self._frames:
            return self._frames.pop(0)
        return False, None

    def release(self):
        self.released.append(1)


def drain(session, until, timeout=5.0):
    """Collect events until ``until(events)`` is true."""
    got, end = [], time.time() + timeout
    while time.time() < end:
        try:
            got.append(session.events.get(timeout=0.05))
        except queue.Empty:
            pass
        if until(got):
            break
    return got


def kinds(events):
    return [k for k, _ in events]


# ---- finding the camera -----------------------------------------------------------------------------------------------------
def test_probes_indexes_and_remembers_the_one_that_works(config_dir):
    tried = []

    def factory(i, b):
        tried.append((i, b))
        return FakeCamera(opens=(i == 2 and b == "any"))
    cam, idx, backend = sc.find_camera(factory)
    assert (idx, backend) == (2, "any")
    assert tried[:5] == [(0, "dshow"), (0, "any"), (1, "dshow"), (1, "any"), (2, "dshow")]      # DirectShow first, then default
    assert sc.load_camera_choice() == (2, "any")
    tried.clear()
    sc.find_camera(factory, remembered=sc.load_camera_choice())
    assert tried[0] == (2, "any")                                                              # tried first next time


def test_no_camera_and_camera_in_use_are_told_apart():
    with pytest.raises(sc.CameraNotFound):
        sc.find_camera(lambda i, b: FakeCamera(opens=False))
    with pytest.raises(sc.CameraInUse):
        sc.find_camera(lambda i, b: FakeCamera(opens=True, frames=[]))                         # opens but never delivers a picture


def test_session_reports_no_camera_in_plain_words_and_ends():
    s = sc.ScannerSession(camera_factory=lambda i, b: FakeCamera(opens=False)).start()
    ev = drain(s, lambda e: "closed" in kinds(e))
    assert ("error", sc.MSG_NO_CAMERA) in ev and kinds(ev)[-1] == "closed"


# ---- scanning -----------------------------------------------------------------------------------------------------------------
def test_code_is_delivered_once_within_two_seconds_then_again_after():
    now = [100.0]
    s = sc.ScannerSession(camera_factory=lambda i, b: FakeCamera(), decode_fn=lambda f: ["Tag ID: CAL-001\nPID: 1"],
                          clock=lambda: now[0], sleep=lambda x: time.sleep(0.001), remember=False).start()
    first = drain(s, lambda e: kinds(e).count("code") >= 1)
    time.sleep(0.2)
    more = drain(s, lambda e: False, timeout=0.3)
    assert kinds(first).count("code") == 1 and kinds(more).count("code") == 0                  # same code ignored at the same instant
    now[0] += 2.5
    later = drain(s, lambda e: kinds(e).count("code") >= 1)
    assert kinds(later).count("code") == 1                                                       # accepted again after 2 s
    s.stop()


def test_frames_never_pile_up_and_frames_arrive():
    s = sc.ScannerSession(camera_factory=lambda i, b: FakeCamera(), decode_fn=lambda f: [], remember=False, frame_every=0).start()
    time.sleep(0.5)
    assert 0 < s.events.qsize() <= 8
    s.stop()


def test_glare_retries_use_preprocessed_variants():
    calls = []

    def decode(frame):
        calls.append(frame.ndim)
        return ["WKR-2026-001"] if len(calls) == 5 else []                                     # only a processed variant reads
    s = sc.ScannerSession(camera_factory=lambda i, b: FakeCamera(), decode_fn=decode, remember=False,
                          sleep=lambda x: time.sleep(0.001)).start()
    ev = drain(s, lambda e: "code" in kinds(e))
    s.stop()
    assert ("code", "WKR-2026-001") in ev
    assert 2 in calls                                                                            # a grayscale / thresholded image was tried


def test_preprocess_variants_shapes():
    out = sc.preprocess_variants(np.random.randint(0, 255, (48, 64, 3), dtype=np.uint8))
    assert len(out) == 4 and all(o.shape == (48, 64) for o in out)


# ---- trouble -------------------------------------------------------------------------------------------------------------------
def test_unplug_mid_scan_reconnects_with_backoff():
    made = []

    def factory(i, b):
        # first camera delivers 3 frames then dies; later ones work
        cam = FakeCamera(frames=[(True, FRAME)] * 3) if not made else FakeCamera()
        made.append(cam)
        return cam
    s = sc.ScannerSession(camera_factory=factory, decode_fn=lambda f: [], remember=False, sleep=lambda x: time.sleep(0.0005)).start()
    ev = drain(s, lambda e: any(k == "status" and "reconnected" in str(p) for k, p in e))
    s.stop()
    assert any("Reconnecting" in str(p) for k, p in ev) and any("reconnected" in str(p) for k, p in ev)
    assert made[0].released                                                                      # the dead camera was released


def test_permanent_unplug_gives_a_clear_error_and_releases():
    released = []
    first = [True]

    def factory(i, b):
        if first[0]:
            first[0] = False
            return FakeCamera(frames=[(True, FRAME)], released=released)
        return FakeCamera(opens=False)
    s = sc.ScannerSession(camera_factory=factory, decode_fn=lambda f: [], remember=False, sleep=lambda x: time.sleep(0.0001)).start()
    ev = drain(s, lambda e: "closed" in kinds(e), timeout=20)
    assert ("error", sc.MSG_LOST) in ev and released


def test_stop_releases_the_camera_and_ends_the_thread():
    released = []
    s = sc.ScannerSession(camera_factory=lambda i, b: FakeCamera(released=released), decode_fn=lambda f: [], remember=False).start()
    drain(s, lambda e: "frame" in kinds(e))
    s.stop()
    assert not s.running and released


def test_decoder_crash_does_not_kill_the_session():
    n = [0]

    def decode(frame):
        n[0] += 1
        if n[0] < 3:
            raise RuntimeError("zbar exploded")
        return ["TAG-1"]
    s = sc.ScannerSession(camera_factory=lambda i, b: FakeCamera(), decode_fn=decode, remember=False,
                          sleep=lambda x: time.sleep(0.001)).start()
    ev = drain(s, lambda e: "code" in kinds(e))
    s.stop()
    assert ("code", "TAG-1") in ev


def test_screen_value_extraction():
    from views.scan_dialog import code_value
    assert code_value("Tag ID: cal-001\nPID: 1\nName: x") == "CAL-001"
    assert code_value("Employee ID: wkr-2026-001") == "WKR-2026-001"
    assert code_value("  hello there!  ") == "hello there!"
