"""Thread and timer hygiene for screens.

``UiMixin`` gives a screen (a frame or window) three guarantees:

  * every ``after()`` job it schedules is remembered and CANCELLED when the screen is destroyed, so a timer can never fire into
    a widget that no longer exists (the "invalid command name" / "application has been destroyed" errors after switching modules);
  * ``post_ui(fn)`` hands a result from a worker thread to the Tk thread safely. Calling ``self.after()`` from a worker thread is
    NOT safe in Tkinter (it fails with "main thread is not in main loop" whenever the loop is busy or idle at the wrong moment);
    ``post_ui`` only puts the callable on a queue, and the screen's own poller runs it on the Tk thread;
  * nothing queued for a destroyed screen is ever run.

Rule for screens: read every widget/Tk variable on the main thread BEFORE starting a worker thread, pass the plain values in, and
return results through ``post_ui``.
"""
import queue

POLL_MS = 50


class UiMixin:
    def _ui_init(self):
        if getattr(self, "_ui_ready", False):
            return
        self._ui_ready = True
        self._ui_queue = queue.Queue()
        self._ui_after_ids = set()
        self._ui_dead = False
        self._ui_poll_id = None
        self._ui_schedule_poll()

    # ---- after() bookkeeping ----------------------------------------------------------------------------------------------------
    def after(self, ms, func=None, *args):
        if func is None or not getattr(self, "_ui_ready", False):       # before _ui_init(): behave exactly like Tk
            return super().after(ms) if func is None else super().after(ms, func, *args)
        holder = {}

        def run():
            self._ui_after_ids.discard(holder.get("id"))
            return func(*args)
        job = super().after(ms, run)
        holder["id"] = job
        self._ui_after_ids.add(job)
        return job

    def after_cancel(self, job):
        if getattr(self, "_ui_ready", False):
            self._ui_after_ids.discard(job)
        try:
            super().after_cancel(job)
        except Exception:
            pass

    # ---- worker thread -> Tk thread ----------------------------------------------------------------------------------------------
    def post_ui(self, fn):
        """Thread-safe. ``fn`` runs on the Tk thread, unless the screen has been destroyed by then."""
        if not getattr(self, "_ui_ready", False):
            raise RuntimeError("UiMixin used from a thread before it was initialised on the main thread")
        if not self._ui_dead:
            self._ui_queue.put(fn)

    def _ui_schedule_poll(self):
        self._ui_poll_id = super().after(POLL_MS, self._ui_poll)

    def _ui_poll(self):
        self._ui_poll_id = None
        if self._ui_dead:
            return
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception:
                    from services.errors import get_logger
                    get_logger().exception("A screen update failed")
        except queue.Empty:
            pass
        if not self._ui_dead:
            self._ui_schedule_poll()

    # ---- teardown -------------------------------------------------------------------------------------------------------------------
    def destroy(self):
        if getattr(self, "_ui_ready", False):
            self._ui_dead = True
            for job in list(self._ui_after_ids) + ([self._ui_poll_id] if self._ui_poll_id else []):
                try:
                    super().after_cancel(job)
                except Exception:
                    pass
            self._ui_after_ids.clear()
            self._ui_poll_id = None
            while True:
                try:
                    self._ui_queue.get_nowait()
                except queue.Empty:
                    break
        super().destroy()
