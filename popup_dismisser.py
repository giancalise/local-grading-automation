"""
popup_dismisser.py
------------------
Background thread that auto-dismisses SolidWorks modal dialogs.

Uses win32api/win32gui directly (faster and more reliable than
pywinauto for blocking dialogs) with pywinauto as fallback.

Confirmed target:
  Title: "SOLIDWORKS Design"  Class: "#32770"  Button: "OK"
  — Student Edition "educational use only" warning

Hardening (SPEC_v0.2 §15.6)
----------------------------
The rule list used to include a bare ("solidworks", "#32770", ["Yes", "OK"])
catch-all that clicked "Yes"/"OK" on ANY dialog whose title merely contained
"solidworks" — which, combined with §15.3's read-only-open guarantee being
new, was a real data-loss path: it would click through a "Save changes?"
prompt it was never meant to answer. That catch-all is gone. Rules below
match specific, known dialog titles only; anything else matching class
#32770 in a SolidWorks-titled window is logged and left alone, never
clicked blind. This was verified against a real, previously-unknown
dialog encountered live during Milestone 1 §16.5 validation (title exactly
"SOLIDWORKS", buttons "&Yes"/"&No") — its meaning is not established, so it
is intentionally NOT auto-dismissed.

Also note: Windows button captions frequently carry a mnemonic ampersand
(e.g. "&Yes") that GetWindowText returns verbatim. Matching must strip it,
or matching silently never fires — this was a real, previously-unnoticed
bug found during the same validation pass.
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
# Rules: (title_exact_lowercase, class_name_or_None, button_texts)
# button_texts is a list tried in order until one is found and clicked.
# Titles are matched EXACTLY (case-insensitive) — no substring catch-alls.
# ---------------------------------------------------------------------------
DISMISS_RULES = [
    # Student Edition "instructional use only" warning — confirmed live,
    # 76 dismissals in the historical agent log.
    ("solidworks design",   "#32770",   ["Yes", "OK"]),
    ("newer version",       None,       ["OK", "Yes"]),
    ("older version",       None,       ["OK", "Yes"]),
]

_POLL_INTERVAL = 0.15   # scan every 150 ms — fast enough to catch popup
_DRAIN_TIME    = 1.5
_UNRECOGNIZED_LOG_INTERVAL = 5.0  # don't spam the log every 150ms


class PopupDismisser:

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_unrecognized_log = 0.0
        # SPEC_v0.2 §15.6 point 2 — a file-open that runs long with zero
        # dismissals is the signature of a UIPI integrity-level mismatch
        # (SendMessage silently doing nothing across elevation boundaries).
        self.dismissal_count = 0

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

            matched = False
            for title_exact, req_class, btn_text in DISMISS_RULES:
                if title != title_exact:
                    continue
                if req_class and class_name != req_class:
                    continue
                matched = True
                # Found a matching dialog — find and click the button
                btn_labels = btn_text if isinstance(btn_text, list) else [btn_text]
                clicked = self._click_button(hwnd, btn_labels)
                if clicked:
                    self.dismissal_count += 1
                    logger.info(
                        "Auto-dismissed: title='%s' class='%s' btn='%s'",
                        win32gui.GetWindowText(hwnd), class_name, clicked,
                    )
                else:
                    logger.warning(
                        "Matched rule for title='%s' class='%s' but found no "
                        "matching button (%s) — possible UIPI mismatch or "
                        "changed dialog layout.",
                        title, class_name, btn_labels,
                    )
                break

            # Log-and-skip: a #32770 dialog in a SolidWorks-titled window
            # that matched no known rule. Never clicked blind (§15.6) —
            # rate-limited so a stuck unknown dialog doesn't spam the log.
            if not matched and class_name == "#32770" and "solidworks" in title:
                now = time.monotonic()
                if now - self._last_unrecognized_log > _UNRECOGNIZED_LOG_INTERVAL:
                    self._last_unrecognized_log = now
                    logger.warning(
                        "Unrecognized SolidWorks dialog NOT dismissed: "
                        "title='%s' class='%s' — add an exact rule if this "
                        "is expected to be auto-answered.",
                        win32gui.GetWindowText(hwnd), class_name,
                    )
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
                txt = win32gui.GetWindowText(hwnd).strip().replace("&", "")
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


def get_dismissal_count() -> int:
    """Total popups auto-dismissed since the dismisser started."""
    return _global_dismisser.dismissal_count if _global_dismisser else 0


# ---------------------------------------------------------------------------
# UIPI integrity-level parity check (SPEC_v0.2 §15.6 point 2)
# ---------------------------------------------------------------------------
# Windows blocks SendMessage/PostMessage across integrity-level (UIPI)
# boundaries. If this process and SolidWorks run at different elevations,
# the dismisser's EnumWindows still finds dialogs — enumeration is not
# blocked — but BM_CLICK silently does nothing, and the first symptom is an
# unexplained hang with zero log entries. This function is a startup
# diagnostic only; it never blocks grading, it just gives the self-test /
# System Ready indicator something concrete to report.

import ctypes
import ctypes.wintypes as wintypes

_TokenIntegrityLevel = 25  # TOKEN_INFORMATION_CLASS.TokenIntegrityLevel
_TOKEN_QUERY = 0x0008
_SECURITY_MANDATORY = {
    0x0000: "Untrusted",
    0x1000: "Low",
    0x2000: "Medium",
    0x3000: "High",
    0x4000: "System",
}


def _process_integrity_level(pid: Optional[int] = None) -> Optional[str]:
    """Best-effort read of a process's integrity level label, or None if
    it can't be determined (e.g. access denied — itself a mismatch signal)."""
    advapi32 = ctypes.windll.advapi32
    kernel32 = ctypes.windll.kernel32

    if pid is None:
        h_process = kernel32.GetCurrentProcess()
        should_close = False
    else:
        h_process = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
        should_close = True
        if not h_process:
            return None

    try:
        h_token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(h_process, _TOKEN_QUERY, ctypes.byref(h_token)):
            return None
        try:
            size = wintypes.DWORD()
            advapi32.GetTokenInformation(h_token, _TokenIntegrityLevel, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(h_token, _TokenIntegrityLevel, buf, size.value, ctypes.byref(size)):
                return None
            # TOKEN_MANDATORY_LABEL.Label.Sid is a PSID at the start of the buffer
            sid_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
            rid_count_ptr = advapi32.GetSidSubAuthorityCount(sid_ptr)
            rid_count = ctypes.cast(rid_count_ptr, ctypes.POINTER(ctypes.c_ubyte))[0]
            rid_ptr = advapi32.GetSidSubAuthority(sid_ptr, rid_count - 1)
            rid = ctypes.cast(rid_ptr, ctypes.POINTER(wintypes.DWORD))[0]
            return _SECURITY_MANDATORY.get(rid & 0xF000, f"Unknown(0x{rid:04x})")
        finally:
            kernel32.CloseHandle(h_token)
    except Exception:
        return None
    finally:
        if should_close and h_process:
            kernel32.CloseHandle(h_process)


def check_integrity_parity(sw_pid: int) -> dict:
    """
    Compare this process's integrity level against SolidWorks'.

    Returns {"self": str|None, "solidworks": str|None, "match": bool|None}.
    match is None (not a hard False) when either level could not be read —
    an unreadable level is itself suspicious (commonly access-denied when
    the other process is HIGHER integrity) and should be surfaced, not
    silently treated as "fine".
    """
    self_level = _process_integrity_level(None)
    sw_level   = _process_integrity_level(sw_pid)
    match = None
    if self_level is not None and sw_level is not None:
        match = self_level == sw_level
    return {"self": self_level, "solidworks": sw_level, "match": match}
