"""
sw_connection.py
----------------
SolidWorks COM connection manager for the MCP grading server.

Responsibilities
----------------
- Attach to an already-running SW instance first (GetActiveObject),
  fall back to launching a new invisible instance (CreateObject).
- Detect ISldWorks.ApplicationType so the same code works in both
  SW Desktop (type 0) and SW Connected / 3DExperience (type 2+).
- Open local .sldprt files silently: no UI, no rebuild prompts,
  no "do you want to save?" dialogs.
- Close documents after each operation without saving.
- Provide a health-check that callers / MCP tools can use before
  attempting any COM call.

NOT in scope here
-----------------
- PLM / 3DExperience cloud-open logic  (all files are local .sldprt)
- Document Manager (SwDocumentMgr) — that lives in dm_connection.py
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import pythoncom
import win32com.client
from popup_dismisser import ensure_dismisser_running

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SW constants we need (defined here so we never rely on the typelib being
# pre-registered in the test environment)
# ---------------------------------------------------------------------------

# IModelDoc2 document types
SW_DOC_PART = 1          # swDocPART
SW_DOC_ASSEMBLY = 2      # swDocASSEMBLY
SW_DOC_DRAWING = 3       # swDocDRAWING

# OpenDoc7 option flags
SW_OPEN_SILENT = 2       # swOpenDocOptions_Silent   — no UI prompts
SW_OPEN_READ_ONLY = 32   # swOpenDocOptions_ReadOnly — no save-back risk

# ISldWorks.ApplicationType values
SW_APP_TYPE_DESKTOP = 0
SW_APP_TYPE_STUDENT = 1              # SolidWorks Student Edition
SW_APP_TYPE_CONNECTED_PLATFORM = 2   # 3DExperience / SW Connected

# Default COM retry parameters
_DEFAULT_CONNECT_RETRIES = 3
_DEFAULT_CONNECT_DELAY_S = 2.0


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------

class SolidWorksConnection:
    """
    Thin wrapper around the ISldWorks COM object.

    Usage
    -----
    conn = SolidWorksConnection()
    conn.connect()          # or use as context manager
    app = conn.application  # ISldWorks
    conn.disconnect()

    Or:
    with SolidWorksConnection() as app:   # yields ISldWorks
        ...
    """

    def __init__(
        self,
        connect_retries: int = _DEFAULT_CONNECT_RETRIES,
        connect_delay_s: float = _DEFAULT_CONNECT_DELAY_S,
        launch_if_not_running: bool = True,
        sw_visible: bool = False,
    ) -> None:
        self._retries = connect_retries
        self._delay = connect_delay_s
        self._launch_if_not_running = launch_if_not_running
        self._sw_visible = sw_visible

        self._app: Optional[win32com.client.CDispatch] = None
        self._application_type: Optional[int] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def application(self) -> win32com.client.CDispatch:
        if self._app is None:
            raise RuntimeError(
                "Not connected to SolidWorks. Call connect() first."
            )
        return self._app

    @property
    def application_type(self) -> Optional[int]:
        """0 = Desktop, 2 = 3DExperience/Connected, None = unknown."""
        return self._application_type

    @property
    def is_connected_platform(self) -> bool:
        return self._application_type == SW_APP_TYPE_CONNECTED_PLATFORM

    @property
    def application_type_label(self) -> str:
        return {
            SW_APP_TYPE_DESKTOP: "Desktop",
            SW_APP_TYPE_STUDENT: "Student Edition",
            SW_APP_TYPE_CONNECTED_PLATFORM: "3DExperience/Connected",
        }.get(self._application_type, f"Unknown (type {self._application_type})")

    def connect(self) -> "SolidWorksConnection":
        """
        Attach to running SW (GetActiveObject) or launch a new instance.
        Retries up to self._retries times with self._delay seconds between
        attempts to handle transient COM registration delays.
        """
        # COM apartments: MTA is safest for background threads but SW
        # macros traditionally run STA. We initialise per-thread here;
        # callers running inside asyncio (MCP server) should call this
        # from the thread that will use the object.
        pythoncom.CoInitialize()

        last_exc: Optional[Exception] = None

        for attempt in range(1, self._retries + 1):
            try:
                self._app = self._try_get_active()
                if self._app is None and self._launch_if_not_running:
                    self._app = self._try_create()
                if self._app is not None:
                    self._detect_application_type()
                    logger.info(
                        "Connected to SolidWorks (attempt %d). "
                        "ApplicationType=%s (%s)",
                        attempt,
                        self._application_type,
                        self.application_type_label,
                    )
                    return self
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "COM connect attempt %d/%d failed: %s",
                    attempt,
                    self._retries,
                    exc,
                )
                if attempt < self._retries:
                    time.sleep(self._delay)

        raise ConnectionError(
            f"Could not connect to SolidWorks after {self._retries} "
            f"attempt(s). Last error: {last_exc}"
        )

    def disconnect(self) -> None:
        """Release COM reference. Does NOT quit SolidWorks."""
        self._app = None
        # Note: we do NOT call CoUninitialize() here because the MCP server
        # process owns the COM apartment for its entire lifetime. Calling
        # CoUninitialize() would break subsequent COM calls in the same process.

    def __enter__(self) -> win32com.client.CDispatch:
        self.connect()
        return self._app  # type: ignore[return-value]

    def __exit__(self, *_: object) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # File open / close helpers  (used by all MCP tools)
    # ------------------------------------------------------------------

    def open_part_silent(
        self,
        filepath: str | Path,
        timeout: float = 45.0,
    ) -> tuple[win32com.client.CDispatch, int]:
        """
        Open a local .sldprt file silently (read-only, no UI).

        Parameters
        ----------
        filepath : absolute path to local .sldprt
        timeout  : seconds to wait before raising SWTimeoutError (default 45)

        Returns
        -------
        (IModelDoc2, error_code)  — error_code 0 means success.

        Raises
        ------
        RuntimeError if not connected.
        FileNotFoundError if the file does not exist on disk.
        SWTimeoutError if SW stalls during open.
        """
        
        path = Path(filepath).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Part file not found: {path}")

        # Call directly on main thread — COM requires CoInitialize on the
        # calling thread, and threading causes silent failures on Student Ed.
        return self._open_part_silent_inner(path)

    def _open_part_silent_inner(
        self, path: Path
    ) -> tuple[win32com.client.CDispatch, int]:
        """Inner open logic."""
        app = self.application

        # Start popup dismisser before opening — handles Student Edition
        # "instructional use only" dialog and other blocking SW popups.
        ensure_dismisser_running()

        doc = None
        err = 0

        # Strategy 1 (SPEC_v0.2 §15.3): OpenDoc6 with Silent|ReadOnly tried
        # FIRST. Student files must never be opened writable — close_doc()
        # already refuses save=True on the promise that opens are read-only;
        # this is what actually keeps that promise. The bare OpenDoc below
        # is a fallback only, and grade_assignment.py additionally grades a
        # scratch copy rather than the original (§15.3 point 2).
        try:
            options = SW_OPEN_SILENT | SW_OPEN_READ_ONLY
            doc = app.OpenDoc6(str(path), SW_DOC_PART, options, "", 0, 0)
            if doc is not None:
                logger.debug("OpenDoc6 (Silent|ReadOnly) succeeded for '%s'", path)
        except Exception as e1:
            logger.debug("OpenDoc6 failed (%s), trying OpenDoc2.", e1)

        # Strategy 2: OpenDoc2 — no out-params, no read-only flag available.
        if doc is None:
            try:
                doc = app.OpenDoc2(str(path), SW_DOC_PART)
                if doc is not None:
                    logger.debug("OpenDoc2 succeeded for '%s'", path)
            except Exception as e2:
                logger.debug("OpenDoc2 failed (%s), trying bare OpenDoc.", e2)

        # Strategy 3: OpenDoc — plain, no suffix, no read-only flag available.
        # Last resort before giving up: opens read-write.
        if doc is None:
            try:
                doc = app.OpenDoc(str(path), SW_DOC_PART)
                if doc is not None:
                    logger.debug("OpenDoc (read-write fallback) succeeded for '%s'", path)
            except Exception as e3:
                logger.debug("OpenDoc failed (%s), checking ActiveDoc.", e3)

        # Strategy 4: file may already be open — grab the active document
        if doc is None:
            try:
                active = app.ActiveDoc
                if active is not None:
                    active_path = active.GetPathName() if hasattr(active, "GetPathName") else ""
                    if str(active_path).lower() == str(path).lower():
                        doc = active
                        logger.debug("Using already-active doc for '%s'", path)
            except Exception:
                pass

        if doc is None:
            raise RuntimeError(
                f"All open strategies failed for '{path}'. "
                "Check that SolidWorks can open this file manually."
            )

        logger.debug("Opened '%s' (err=%d)", path, err)
        return doc, err

    def close_doc(self, filepath: str | Path, save: bool = False) -> None:
        """
        Close an open document without saving (default).

        Parameters
        ----------
        filepath : the same absolute path that was passed to open_part_silent.
        save     : MUST remain False for all grading operations.
        """
        if save:
            raise ValueError(
                "save=True is forbidden in the grading server — "
                "student files must never be modified."
            )
        try:
            app = self.application
            app.CloseDoc(str(Path(filepath).resolve()))
        except Exception as exc:  # noqa: BLE001
            # Log but don't re-raise: failing to close is unfortunate but
            # not fatal for the grader's result.
            logger.warning("CloseDoc failed for '%s': %s", filepath, exc)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _try_get_active(self) -> Optional[win32com.client.CDispatch]:
        """Attach to a running SW instance without launching a new one."""
        try:
            # Force late binding — early binding (gencache) breaks OpenDoc
            # on Student Edition. Use dynamic dispatch only.
            app = win32com.client.dynamic.Dispatch("SldWorks.Application")
            # Verify it's actually connected to a running instance
            _ = app.RevisionNumber
            logger.debug("GetActiveObject('SldWorks.Application') succeeded.")
            return app
        except pythoncom.com_error as exc:
            # 0x800401E3 = MK_E_UNAVAILABLE (not running)
            logger.debug("No running SW instance found: %s", exc)
            return None

    def _try_create(self) -> Optional[win32com.client.CDispatch]:
        """Launch a new SW instance."""
        logger.info("Launching new SolidWorks instance (visible=%s)…", self._sw_visible)
        app = win32com.client.dynamic.Dispatch("SldWorks.Application")
        app.Visible = self._sw_visible
        # Give SW a moment to finish initialising before we hit it with API calls
        time.sleep(3)
        return app

    def _detect_application_type(self) -> None:
        """
        Read ISldWorks.ApplicationType.
        0 = SW Desktop, 2 = SW Connected / 3DExperience.
        Silently falls back to None if the property is unavailable
        (older SW versions don't expose it).
        """
        try:
            self._application_type = int(self._app.ApplicationType)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            self._application_type = None
            logger.debug("ApplicationType property not available on this SW version.")


# ---------------------------------------------------------------------------
# Module-level singleton  (shared across all MCP tool calls in the process)
# ---------------------------------------------------------------------------

_singleton: Optional[SolidWorksConnection] = None


def get_connection(
    launch_if_not_running: bool = True,
    sw_visible: bool = False,
) -> SolidWorksConnection:
    """
    Return the module-level SolidWorksConnection, connecting if needed.
    Automatically recovers if SW has crashed or become unresponsive.

    This is the function MCP tools should call:

        conn = get_connection()
        doc, err = conn.open_part_silent(filepath)
        ...
        conn.close_doc(filepath)
    """
    global _singleton  # noqa: PLW0603

    # Check if existing connection is still alive
    if _singleton is not None and _singleton._app is not None:
        if not _is_sw_alive(_singleton._app):
            logger.warning("SW connection lost — resetting and reconnecting.")
            try:
                _singleton.disconnect()
            except Exception:
                pass
            _singleton = None

    if _singleton is None or _singleton._app is None:
        _singleton = SolidWorksConnection(
            launch_if_not_running=launch_if_not_running,
            sw_visible=sw_visible,
        )
        _singleton.connect()
    return _singleton


def _is_sw_alive(app) -> bool:
    """
    Quick liveness check — ping SW with a cheap property read.
    Returns False if SW has crashed, hung, or become inaccessible.
    """
    try:
        # RevisionNumber is the cheapest readable property
        _ = app.RevisionNumber
        return True
    except Exception:
        return False


def reset_connection() -> None:
    """Force a fresh connection on the next get_connection() call."""
    global _singleton  # noqa: PLW0603
    if _singleton is not None:
        _singleton.disconnect()
    _singleton = None


# ---------------------------------------------------------------------------
# Convenience context manager for one-shot operations
# ---------------------------------------------------------------------------

@contextmanager
def open_part(filepath: str | Path):
    """
    Context manager that opens a part, yields (IModelDoc2, connection),
    and closes the part on exit — even if an exception is raised.

    Example
    -------
    with open_part(filepath) as (doc, conn):
        mass_props = doc.Extension.CreateMassProperty()
        ...
    # doc is closed here automatically
    """
    conn = get_connection()
    doc, _ = conn.open_part_silent(filepath)
    try:
        yield doc, conn
    finally:
        conn.close_doc(filepath)


# ---------------------------------------------------------------------------
# Health check (used by the MCP solidworks_running tool)
# ---------------------------------------------------------------------------

def solidworks_health_check() -> dict:
    """
    Return a status dict describing the current SW COM accessibility.

    Returns
    -------
    {
        "running": bool,
        "application_type": int | None,
        "application_type_label": str,
        "version": str | None,
        "error": str | None
    }
    """
    result: dict = {
        "running": False,
        "application_type": None,
        "application_type_label": "unknown",
        "version": None,
        "error": None,
    }
    try:
        pythoncom.CoInitialize()
        app = win32com.client.dynamic.Dispatch("SldWorks.Application")
        _ = app.RevisionNumber  # verify connection
        result["running"] = True

        try:
            app_type = int(app.ApplicationType)
            result["application_type"] = app_type
            result["application_type_label"] = {
                SW_APP_TYPE_DESKTOP: "Desktop",
                SW_APP_TYPE_STUDENT: "Student Edition",
                SW_APP_TYPE_CONNECTED_PLATFORM: "3DExperience/Connected",
            }.get(app_type, f"Unknown (type {app_type})")
        except Exception:  # noqa: BLE001
            result["application_type_label"] = "unknown (property unavailable)"

        try:
            result["version"] = str(app.RevisionNumber)
        except Exception:  # noqa: BLE001
            pass

    except pythoncom.com_error as exc:
        result["error"] = f"SolidWorks not reachable via COM: {exc}"
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    return result


# ---------------------------------------------------------------------------
# Crash recovery utilities
# ---------------------------------------------------------------------------

def close_all_docs() -> int:
    """
    Close all open documents in SW without saving.
    Useful for cleanup after a crash or stall.
    Returns number of documents closed.
    """
    try:
        conn = get_connection()
        app = conn.application
        closed = 0
        # Get all open doc paths
        try:
            docs = app.GetDocuments
            if callable(docs): docs = app.GetDocuments()
            if docs:
                paths = [d.GetPathName if not callable(d.GetPathName)
                         else d.GetPathName() for d in docs]
                for path in paths:
                    if path:
                        try:
                            app.CloseDoc(path)
                            closed += 1
                        except Exception:
                            pass
        except Exception:
            pass
        return closed
    except Exception as exc:
        logger.warning("close_all_docs failed: %s", exc)
        return 0


def recover_from_stall(timeout_s: float = 5.0) -> bool:
    """
    Attempt to recover from a SW stall.
    - Pings SW with a timeout
    - Resets the connection if unresponsive
    - Returns True if recovery succeeded, False if SW needs restart
    """
    global _singleton

    import threading

    result = {"alive": False}

    def ping():
        try:
            if _singleton and _singleton._app:
                _ = _singleton._app.RevisionNumber
                result["alive"] = True
        except Exception:
            pass

    t = threading.Thread(target=ping, daemon=True)
    t.start()
    t.join(timeout=timeout_s)

    if result["alive"]:
        return True

    logger.warning("SW appears stalled — resetting connection.")
    try:
        if _singleton:
            _singleton._app = None
            _singleton = None
    except Exception:
        pass

    # Try to reconnect
    try:
        get_connection()
        return True
    except Exception as exc:
        logger.error("SW recovery failed: %s. Please restart SolidWorks.", exc)
        return False
