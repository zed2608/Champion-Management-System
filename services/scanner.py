"""One QR scanner for the whole app (login badge, issuance, retrieval, inventory).

[UNHAPPY-PATH] Before this each screen opened its own camera on index 0, blocked the window while it ran, never recovered from an
unplugged camera, read the same code many times a second and gave up on glare. Here:

  * the camera is read in a WORKER THREAD; it never touches Tk. Results come back through a ``queue.Queue`` that the screen polls
    with ``after()`` (see ``views/scan_dialog.py``);
  * camera indexes 0-3 are probed (DirectShow first, then the default backend); the index that worked is remembered in
    ``scanner_config.json`` (git-ignored, per computer);
  * "no camera" and "camera is in use by another program" are told apart and explained;
  * a camera unplugged mid-scan is retried with a growing delay, then reported;
  * the same code is ignored for 2 seconds after it was reported (debounce);
  * a frame that does not decode is retried after grayscale, CLAHE contrast, adaptive threshold and sharpening (glare, smudges);
  * the camera is ALWAYS released (``finally`` and ``stop()``).

Events put on the queue are ``(kind, payload)``: ``("frame", rgb_array)``, ``("code", text)``, ``("status", text)``,
``("error", text)`` (fatal: the session has ended) and ``("closed", None)`` (always the last event).
"""
import json
import os
import queue
import threading
import time
from pathlib import Path

from services.errors import PROJECT_ROOT, get_logger

CONFIG_NAME = "scanner_config.json"
INDEXES = (0, 1, 2, 3)
DEBOUNCE_SECONDS = 2.0
MAX_RECONNECT_ATTEMPTS = 6
FAILED_READS_BEFORE_RECONNECT = 8

MSG_NO_CAMERA = ("Camera not found. Check that a webcam is plugged in and switched on, then try again. "
                 "You can still type the ID in the box.")
MSG_IN_USE = ("The camera is in use by another program (for example a video call or another scanner window). "
              "Close it and try again. You can still type the ID in the box.")
MSG_LOST = "The camera was unplugged or stopped answering. Reconnect it and press Scan again. You can still type the ID in the box."


class CameraNotFound(Exception):
    pass


class CameraInUse(Exception):
    pass


# ---- local config (remembered camera) -------------------------------------------------------------------------------------
def config_path() -> Path:
    return Path(os.environ.get("CHAMPION_CONFIG_DIR") or PROJECT_ROOT) / CONFIG_NAME


def load_camera_choice():
    """(index, backend_name) last known to work, or None."""
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        idx, backend = int(data["camera_index"]), str(data["backend"])
        return (idx, backend) if idx in INDEXES else None
    except Exception:
        return None


def save_camera_choice(index, backend):
    try:
        config_path().write_text(json.dumps({"camera_index": int(index), "backend": backend}), encoding="utf-8")
    except Exception:
        get_logger().warning("Could not remember the working camera")      # not fatal


# ---- cameras ----------------------------------------------------------------------------------------------------------------
class CvCamera:
    """Real webcam through OpenCV. Any object with open()/read()/release() can replace it (tests use a fake)."""

    def __init__(self, index, backend):
        self.index, self.backend, self._cap = index, backend, None

    def open(self):
        import cv2
        api = cv2.CAP_DSHOW if self.backend == "dshow" and hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(self.index, api)
        if self._cap is not None and self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            return True
        self.release()
        return False

    def read(self):
        if self._cap is None:
            return False, None
        try:
            return self._cap.read()
        except Exception:
            return False, None

    def release(self):
        cap, self._cap = self._cap, None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


def default_camera_factory(index, backend):
    return CvCamera(index, backend)


def find_camera(factory=default_camera_factory, indexes=INDEXES, remembered=None, remember=True):
    """Open the first working camera. Returns (camera, index, backend); raises CameraInUse / CameraNotFound.
    A device that opens but never delivers a picture is reported as 'in use' (the usual cause on Windows)."""
    attempts = [(i, b) for i in indexes for b in ("dshow", "any")]
    if remembered and remembered in attempts:
        attempts.remove(remembered)
        attempts.insert(0, remembered)
    opened_without_picture = False
    for index, backend in attempts:
        cam = factory(index, backend)
        try:
            if not cam.open():
                cam.release()
                continue
            for _ in range(5):                              # a camera needs a moment to start delivering
                ok, frame = cam.read()
                if ok and frame is not None:
                    if remember:
                        save_camera_choice(index, backend)
                    return cam, index, backend
                time.sleep(0.05)
            opened_without_picture = True
        except Exception:
            get_logger().warning("Camera %s/%s failed to open", index, backend, exc_info=True)
        cam.release()
    raise CameraInUse(MSG_IN_USE) if opened_without_picture else CameraNotFound(MSG_NO_CAMERA)


# ---- decoding ----------------------------------------------------------------------------------------------------------------
def default_decode(frame):
    """Text of every QR code in ``frame`` (pyzbar). Imported late so the rest of the app starts without it."""
    from pyzbar.pyzbar import decode, ZBarSymbol
    return [o.data.decode("utf-8", "replace") for o in decode(frame, symbols=[ZBarSymbol.QRCODE])]


def preprocess_variants(frame):
    """Alternative views of the same frame for glare / smudges: grayscale, CLAHE, adaptive threshold, sharpen."""
    import cv2
    import numpy as np
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    adaptive = cv2.adaptiveThreshold(clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    sharp = cv2.filter2D(gray, -1, kernel)
    return [gray, clahe, adaptive, sharp]


# ---- the session ------------------------------------------------------------------------------------------------------------
class ScannerSession:
    """Owns one camera and one worker thread. ``events`` is the queue the screen polls. Create, ``start()``, poll, ``stop()``."""

    def __init__(self, camera_factory=default_camera_factory, decode_fn=default_decode, variants_fn=preprocess_variants,
                 clock=time.monotonic, sleep=time.sleep, indexes=INDEXES, frame_every=0.06, remember=True):
        self.events = queue.Queue()
        self._factory, self._decode, self._variants = camera_factory, decode_fn, variants_fn
        self._clock, self._sleep, self._indexes = clock, sleep, indexes
        self._frame_every, self._remember = frame_every, remember
        self._stop = threading.Event()
        self._thread = None
        self._camera = None
        self._last_seen = {}
        self.camera_info = None

    # public ---------------------------------------------------------------------------------------------------------------
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="qr-scanner", daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout=3.0):
        """Ask the worker to finish and wait for it; the camera is released by the worker (and here as a safety net)."""
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout)
        cam, self._camera = self._camera, None
        if cam is not None and (t is None or not t.is_alive()):
            cam.release()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    # internals ------------------------------------------------------------------------------------------------------------
    def _emit(self, kind, payload=None):
        self.events.put((kind, payload))

    def _accept(self, text):
        """2-second debounce per code."""
        now = self._clock()
        last = self._last_seen.get(text)
        self._last_seen[text] = now
        return last is None or now - last >= DEBOUNCE_SECONDS

    def _decode_frame(self, frame, n):
        try:
            codes = self._decode(frame)
        except Exception:
            get_logger().warning("QR decode failed", exc_info=True)
            codes = []
        if codes or n % 3:                                  # glare / smudge retries only on every 3rd empty frame (saves CPU)
            return codes
        try:
            for variant in self._variants(frame):
                codes = self._decode(variant)
                if codes:
                    return codes
        except Exception:
            get_logger().warning("QR retry failed", exc_info=True)
        return []

    def _open(self):
        remembered = load_camera_choice()
        cam, index, backend = find_camera(self._factory, self._indexes, remembered, self._remember)
        self._camera, self.camera_info = cam, (index, backend)
        return cam

    def _reconnect(self):
        """Backoff 0.5, 1, 2, 4, 4, 4 s. True when a camera is back."""
        old, self._camera = self._camera, None
        if old is not None:
            old.release()
        delay = 0.5
        for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
            if self._stop.is_set():
                return False
            self._emit("status", f"Camera disconnected. Reconnecting (attempt {attempt} of {MAX_RECONNECT_ATTEMPTS})...")
            waited = 0.0
            while waited < delay and not self._stop.is_set():
                self._sleep(0.05)
                waited += 0.05
            try:
                self._open()
                self._emit("status", "Camera reconnected.")
                return True
            except (CameraNotFound, CameraInUse):
                delay = min(delay * 2, 4.0)
        return False

    def _run(self):
        try:
            try:
                self._open()
            except (CameraNotFound, CameraInUse) as e:
                self._emit("error", str(e))
                return
            self._emit("status", "Point the QR code at the camera.")
            failed, n, last_frame = 0, 0, 0.0
            while not self._stop.is_set():
                ok, frame = self._camera.read()
                if not ok or frame is None:
                    failed += 1
                    if failed >= FAILED_READS_BEFORE_RECONNECT:
                        if not self._reconnect():
                            if not self._stop.is_set():
                                self._emit("error", MSG_LOST)
                            return
                        failed = 0
                    else:
                        self._sleep(0.05)
                    continue
                failed, n = 0, n + 1
                for text in self._decode_frame(frame, n):
                    text = text.strip()
                    if text and self._accept(text):
                        self._emit("code", text)
                now = self._clock()
                if now - last_frame >= self._frame_every and self.events.qsize() < 6:    # never let pictures pile up
                    last_frame = now
                    self._emit("frame", frame)
                self._sleep(0.005)
        except Exception:
            get_logger().exception("Scanner worker crashed")
            self._emit("error", "The scanner stopped unexpectedly. Close this window and try again.")
        finally:
            cam, self._camera = self._camera, None
            if cam is not None:
                try:
                    cam.release()
                except Exception:
                    pass
            self._emit("closed")
