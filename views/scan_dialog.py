"""The one scan window used by login, issuance, retrieval and inventory.

The camera runs in services.scanner's worker thread; this window only polls its queue with ``after()`` on the Tk thread.
"""
import queue

import customtkinter as ctk
from PIL import Image

from services import validators as v
from services.scanner import ScannerSession
from ui import components as C
from ui import theme as T

POLL_MS = 30


def code_value(raw):
    """What a screen should put in its text box for a scanned payload: the Tag ID / Employee ID line, else the trimmed text."""
    scan = v.parse_scan(raw)
    return scan.value if scan.kind in ("tool", "worker") else (raw or "").strip()


class ScanDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_code, title="Scan QR Code", session_factory=ScannerSession, single_shot=True):
        super().__init__(parent)
        self.title(title)
        C.fit_window(self, 450, 470)
        C.keep_above(self, parent)
        self._previous_grab = parent.grab_current()
        self.grab_set()
        self._on_code, self._single_shot = on_code, single_shot
        self._job = None
        self._closed = False
        ctk.CTkLabel(self, text="Align the QR code with the camera", font=T.font(14, "bold")).pack(pady=(16, 6))
        self.video = ctk.CTkLabel(self, text="Starting camera...", font=T.font(12), text_color=T.TEXT_MUTED, width=400, height=300)
        self.video.pack(padx=20)
        self.status = ctk.CTkLabel(self, text="", font=T.font(12), text_color=T.TEXT_SECONDARY, wraplength=400, justify="left")
        self.status.pack(fill="x", padx=20, pady=8)
        C.button(self, kind="secondary", text="Cancel", command=self.close).pack(pady=(0, 12))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.session = session_factory()
        self.session.start()
        self._job = self.after(POLL_MS, self._poll)

    def _poll(self):
        self._job = None
        if self._closed:
            return
        latest_frame, finished = None, False
        try:
            while True:
                kind, payload = self.session.events.get_nowait()
                if kind == "frame":
                    latest_frame = payload
                elif kind == "code":
                    if self._deliver(payload):
                        return
                elif kind == "status":
                    self.status.configure(text=payload, text_color=T.TEXT_SECONDARY)
                elif kind == "error":
                    self.video.configure(image=None, text="No picture")
                    self.status.configure(text=payload, text_color=T.DANGER_TEXT)
                elif kind == "closed":
                    finished = True
        except queue.Empty:
            pass
        if latest_frame is not None:
            self._show(latest_frame)
        if not finished:
            self._job = self.after(POLL_MS, self._poll)

    def _show(self, frame):
        try:
            rgb = frame[:, :, ::-1] if frame.ndim == 3 else frame
            img = ctk.CTkImage(light_image=Image.fromarray(rgb), size=(400, 300))
            self.video.configure(image=img, text="")
            self.video.image = img                           # keep a reference
        except Exception:
            pass

    def _deliver(self, raw):
        if self._single_shot:
            self.close()
        try:
            self._on_code(code_value(raw))
        except Exception:
            from services.errors import get_logger
            get_logger().exception("Scan callback failed")
        return self._single_shot

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        try:
            self.session.stop()                              # releases the camera
        finally:
            try:
                self.destroy()
            except Exception:
                pass
            if self._previous_grab is not None:
                try:
                    if self._previous_grab.winfo_exists():
                        self._previous_grab.grab_set()
                        self._previous_grab.lift()
                        self._previous_grab.focus_force()
                except Exception:
                    pass


def open_scan_dialog(parent, on_code, title="Scan QR Code", **kw):
    return ScanDialog(parent, on_code, title, **kw)
