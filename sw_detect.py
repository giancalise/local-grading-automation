"""
sw_detect.py
------------
SolidWorks detection for the System Ready indicator (SPEC_v0.2 §3.2).

Critical correction from v0.1, confirmed empirically during Milestone 1
§16.5 live COM validation on this machine:

  win32com.client.dynamic.Dispatch("SldWorks.Application") is
  CoCreateInstance. For a registered local server, calling it when
  SolidWorks is NOT running launches it — Dispatch is not a passive
  "is it running" check. Worse, on THIS machine's SolidWorks
  3DEXPERIENCE-integrated install, a raw Dispatch()-triggered launch
  bypasses the platform-auth bootstrap the real Start Menu shortcut
  performs (CATSTART.exe -> SWXDesktopLauncher.exe), which surfaces a
  blocking dialog and reliably crashes the new instance after 60-130s
  (observed 3 times: com_error -2146959355 "Server execution failed").
  Direct sldworks.exe launches were also unreliable here.

  pythoncom.GetActiveObject("SldWorks.Application") is the correct
  "is it running" detector — verified live to (a) never launch anything
  when SW is not running (correctly fails MK_E_UNAVAILABLE instead), and
  (b) attach instantly when SW is genuinely running. Only GetActiveObject
  is used below for the running-state check.

  For the Launch action, this module shells out to the real Start Menu
  shortcut when one can be found (reproducing the bootstrap a human
  double-click performs), falling back to the bare registered exe only
  if no shortcut is found — see launch_solidworks().
"""

from __future__ import annotations

import glob
import logging
import os
import subprocess
import winreg
from typing import Optional

import pythoncom
import win32com.client

logger = logging.getLogger(__name__)

# ApplicationType values (sw_connection.py has the same constants; kept
# duplicated here rather than importing sw_connection, since this module
# must work even before a connection singleton exists).
SW_APP_TYPE_DESKTOP = 0
SW_APP_TYPE_STUDENT = 1
SW_APP_TYPE_CONNECTED_PLATFORM = 2

_APP_TYPE_LABELS = {
    SW_APP_TYPE_DESKTOP: "Desktop",
    SW_APP_TYPE_STUDENT: "Student Edition",
    SW_APP_TYPE_CONNECTED_PLATFORM: "3DExperience / Connected",
}

# Build-number -> release-year mapping (SPEC_v0.2 §3.2). RevisionNumber
# returns a build number like "34.3.0", not a year. Anchor point confirmed
# empirically on this machine: RevisionNumber major version 34 corresponds
# to "SOLIDWORKS 2026" (registry key name and main window title both say
# 2026; ApplicationType=1, matching every historical Discovery log).
# Adjacent years follow SolidWorks' well-known one-major-version-per-year
# numbering (not independently verified on other machines this session —
# flag as unconfirmed if it matters).
_BUILD_TO_YEAR = {
    28: 2020, 29: 2021, 30: 2022, 31: 2023, 32: 2024, 33: 2025, 34: 2026, 35: 2027,
}


def _major_version(revision_number: str) -> Optional[int]:
    try:
        return int(str(revision_number).split(".")[0])
    except (ValueError, IndexError):
        return None


def build_number_to_year(revision_number: Optional[str]) -> Optional[int]:
    if not revision_number:
        return None
    major = _major_version(revision_number)
    if major is None:
        return None
    return _BUILD_TO_YEAR.get(major)


# ---------------------------------------------------------------------------
# Installed?
# ---------------------------------------------------------------------------

def is_installed() -> dict:
    """
    Registry probe (SPEC_v0.2 §3.2): resolve the SldWorks.Application
    ProgID to a CLSID and confirm it has a LocalServer32 entry. This is
    edition-agnostic — it doesn't depend on parsing a version-specific
    subkey name under HKLM\\SOFTWARE\\SolidWorks, which varies by release
    and install channel (this machine's is "SOLIDWORKS 2026", but that
    string isn't guaranteed on another install).
    """
    result = {"installed": False, "exe_path": None, "clsid": None, "error": None}
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application\CLSID") as k:
            clsid, _ = winreg.QueryValueEx(k, "")
        result["clsid"] = clsid
        with winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32"
        ) as k:
            exe_path, _ = winreg.QueryValueEx(k, "")
        result["exe_path"] = exe_path
        result["installed"] = True
    except FileNotFoundError:
        result["error"] = "SldWorks.Application ProgID not registered — SolidWorks not installed."
    except Exception as exc:
        result["error"] = str(exc)
    return result


# ---------------------------------------------------------------------------
# Running?
# ---------------------------------------------------------------------------

def is_running() -> dict:
    """
    GetActiveObject only — never Dispatch. Confirmed live (see module
    docstring) that this correctly does NOT launch SolidWorks as a side
    effect of checking.
    """
    result = {
        "running": False,
        "application_type": None,
        "application_type_label": None,
        "revision_number": None,
        "release_year": None,
        "error": None,
    }
    try:
        pythoncom.CoInitialize()
    except Exception:
        pass

    try:
        app = win32com.client.GetActiveObject("SldWorks.Application")
        result["running"] = True
        try:
            result["revision_number"] = str(app.RevisionNumber)
            result["release_year"] = build_number_to_year(result["revision_number"])
        except Exception as exc:
            logger.debug("RevisionNumber read failed: %s", exc)
        try:
            app_type = int(app.ApplicationType)
            result["application_type"] = app_type
            result["application_type_label"] = _APP_TYPE_LABELS.get(
                app_type, f"Unknown (type {app_type})"
            )
        except Exception as exc:
            logger.debug("ApplicationType read failed: %s", exc)
    except pythoncom.com_error as exc:
        # MK_E_UNAVAILABLE (-2147221021 / 0x800401E3) = not running. Any
        # other com_error is surfaced rather than silently treated as "not
        # running" — that distinction matters for diagnosing real faults.
        if exc.hresult == -2147221021:
            result["error"] = None
        else:
            result["error"] = f"Unexpected COM error checking SolidWorks: {exc}"
    except Exception as exc:
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def _find_start_menu_shortcut() -> Optional[str]:
    """
    Find the real SolidWorks Start Menu shortcut, which (on this machine's
    3DEXPERIENCE-integrated install) bootstraps through CATSTART.exe /
    SWXDesktopLauncher.exe before the SldWorks process comes up — the path
    a raw Dispatch()/exe launch skips, which is what caused the crash
    observed during Milestone 1 validation. Falls back to None if no
    "SOLIDWORKS Design"-ish shortcut is found; caller falls back to the
    registered exe directly.
    """
    search_roots = [
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                      "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.environ.get("APPDATA", ""),
                      "Microsoft", "Windows", "Start Menu", "Programs"),
    ]
    candidates = []
    for root in search_roots:
        if not root or not os.path.isdir(root):
            continue
        for path in glob.glob(os.path.join(root, "**", "*.lnk"), recursive=True):
            name = os.path.basename(path).lower()
            if "solidworks" in name and "design" in name:
                candidates.append(path)
            elif "solidworks" in name and "visualize" not in name and "task" not in name \
                    and "rx" not in name and "wizard" not in name and "performance" not in name:
                candidates.append(path)
    # Prefer a shortcut with "Design" in the name (the actual application,
    # not Visualize/Rx/Task Scheduler/Settings Wizard/Performance Test).
    candidates.sort(key=lambda p: ("design" not in p.lower(), p))
    return candidates[0] if candidates else None


def launch_solidworks() -> dict:
    """
    Start a SolidWorks instance. Prefers the real Start Menu shortcut
    (reproduces the platform-auth bootstrap a human launch performs);
    falls back to the bare registered exe, which is empirically less
    reliable on this edition but is the only option if no shortcut exists.

    Does not wait for COM to respond — callers should poll is_running().
    """
    result = {"started": False, "method": None, "error": None}

    shortcut = _find_start_menu_shortcut()
    if shortcut:
        try:
            os.startfile(shortcut)
            result["started"] = True
            result["method"] = f"start_menu_shortcut: {shortcut}"
            return result
        except Exception as exc:
            logger.warning("Launching via shortcut failed (%s), falling back to exe.", exc)

    installed = is_installed()
    if not installed["installed"] or not installed["exe_path"]:
        result["error"] = "SolidWorks is not installed (no registered LocalServer32)."
        return result

    exe_path = installed["exe_path"].strip('"')
    try:
        subprocess.Popen([exe_path], close_fds=True)
        result["started"] = True
        result["method"] = f"direct_exe: {exe_path}"
        result["error"] = (
            "Launched via the registered executable directly, not the "
            "Start Menu shortcut — this path was observed to be less "
            "reliable during validation (may show a startup dialog that "
            "needs manual dismissal, or take several minutes)."
        )
    except Exception as exc:
        result["error"] = f"Failed to launch SolidWorks: {exc}"

    return result
