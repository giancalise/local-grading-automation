"""
popup_dismisser.py
------------------
Background thread that auto-dismisses SolidWorks modal dialogs.

Uses win32api/win32gui directly (faster and more reliable than
pywinauto for blocking dialogs) with pywinauto as fallback.

Confirmed target:
  Title: "SOLIDWORKS Design"  Class: "#32770"  Button: "OK"
  — Student Edition "educational use only" warning
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import win32api
import win32con
import win32gui

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rules: (title_fragment_lowercase, class_name_or_None, button_texts)
# button_texts is a list tried in order until one is found and clicked.
# ---------------------------------------------------------------------------
DISMISS_RULES = [
    # "SOLIDWORKS Design" covers both:
    #   - Student Edition "instructional use only" warning  → button: OK
    #   - Low memory warning "Do you want to continue?"     → button: Yes
    ("solidworks design",   "#32770",   ["Yes", "OK"]),
    ("solidworks",          "#32770",   ["Yes", "OK"]),
    ("newer version",       None,       ["OK", "Yes"]),
    ("older version",       None,       ["OK", "Yes"]),
]

_POLL_INTERVAL = 0.15   # scan every 150 ms — fast enough to catch popup
_DRAIN_TIME    = 1.5


class PopupDismisser:

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "PopupDismisser":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop,
            name="SW-PopupDismisser",
            daemon=True,
        )
        self._thread.start()
        # Give the thread a moment to start scanning before caller proceeds
        time.sleep(0.1)
        logger.debug("PopupDismisser started.")

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop_event.set()
        self._thread.join(timeout=_DRAIN_TIME + 1.0)
        self._thread = None

    # ------------------------------------------------------------------

    def _watch_loop(self) -> None:
        drain_start: Optional[float] = None
        while True:
            if self._stop_event.is_set():
                if drain_start is None:
                    drain_start = time.monotonic()
                elif time.monotonic() - drain_start > _DRAIN_TIME:
                    break
            self._scan_and_dismiss()
            time.sleep(_POLL_INTERVAL)

    def _scan_and_dismiss(self) -> None:
        """Enumerate top-level windows and click OK on matching dialogs."""
        def callback(hwnd: int, _: object) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True

            try:
                title = win32gui.GetWindowText(hwnd).lower()
                class_name = win32gui.GetClassName(hwnd)
            except Exception:
                return True

            for title_frag, req_class, btn_text in DISMISS_RULES:
                if title_frag not in title:
                    continue
                if req_class and class_name != req_class:
                    continue
                # Found a matching dialog — find and click the button
                btn_labels = btn_text if isinstance(btn_text, list) else [btn_text]
                clicked = self._click_button(hwnd, btn_labels)
                if clicked:
                    logger.info(
                        "Auto-dismissed: title='%s' class='%s' btn='%s'",
                        win32gui.GetWindowText(hwnd), class_name, clicked,
                    )
                break
            return True

        try:
            win32gui.EnumWindows(callback, None)
        except Exception as exc:
            logger.debug("EnumWindows error: %s", exc)

    def _click_button(self, parent_hwnd: int, button_texts) -> str | None:
        """Find a child button by text and send BM_CLICK. Returns clicked label or None."""
        if isinstance(button_texts, str):
            button_texts = [button_texts]
        result = {"clicked": None}

        def child_callback(hwnd: int, _: object) -> bool:
            try:
                cls = win32gui.GetClassName(hwnd)
                txt = win32gui.GetWindowText(hwnd).strip()
                if cls == "Button" and txt in button_texts:
                    # Send click message directly — works even if window
                    # is behind others or not focused
                    win32api.SendMessage(hwnd, win32con.BM_CLICK, 0, 0)
                    result["clicked"] = txt
                    return False  # stop enumeration
            except Exception:
                pass
            return True

        try:
            win32gui.EnumChildWindows(parent_hwnd, child_callback, None)
        except Exception:
            pass

        return result["clicked"]  # None if not clicked, label string if clicked


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_global_dismisser: Optional[PopupDismisser] = None


def ensure_dismisser_running() -> None:
    global _global_dismisser
    if _global_dismisser is None:
        _global_dismisser = PopupDismisser()
    if not (_global_dismisser._thread and _global_dismisser._thread.is_alive()):
        _global_dismisser.start()


def stop_dismisser() -> None:
    global _global_dismisser
    if _global_dismisser:
        _global_dismisser.stop()
        _global_dismisser = None
