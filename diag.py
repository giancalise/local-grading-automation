"""
diag.py
-------
Diagnostic script for the SolidWorks MCP grading server.
Run this to verify COM connectivity, file open strategies, and
metadata reading before wiring up the full MCP server.

Usage:
    python diag.py
"""

import pprint
import pythoncom
import win32com.client

# Must be called once per thread before any COM operations.
# Call it here and never call CoUninitialize() in this script —
# we own the COM apartment for the lifetime of this process.
pythoncom.CoInitialize()
from pathlib import Path

PATH = r'C:\Users\gce4\Box\ES-19\CADFiles\Listed\0253.SLDPRT'
SW_DOC_PART = 1
SW_OPEN_SILENT = 2
SW_OPEN_READ_ONLY = 32

print("=" * 60)
print("SECTION 1: SolidWorks health check")
print("=" * 60)
from sw_connection import solidworks_health_check
pprint.pprint(solidworks_health_check())

print()
print("=" * 60)
print("SECTION 2: File check")
print("=" * 60)
p = Path(PATH)
print(f"Exists:    {p.exists()}")
print(f"Size:      {p.stat().st_size if p.exists() else 'n/a'} bytes")
print(f"Extension: {p.suffix}")

print()
print("=" * 60)
print("SECTION 3: Popup dismisser startup")
print("=" * 60)
try:
    from popup_dismisser import ensure_dismisser_running
    ensure_dismisser_running()
    print("Popup dismisser: RUNNING")
except Exception as e:
    print(f"Popup dismisser: FAILED — {e}")

print()
print("=" * 60)
print("SECTION 4: Open strategy tests (close SW file first!)")
print("=" * 60)
app = win32com.client.GetActiveObject("SldWorks.Application")
print(f"SW version: {app.RevisionNumber}")

strategies = [
    ("OpenDoc",  lambda: app.OpenDoc(PATH, SW_DOC_PART)),
    ("OpenDoc2", lambda: app.OpenDoc2(PATH, SW_DOC_PART)),
    ("OpenDoc6", lambda: app.OpenDoc6(PATH, SW_DOC_PART, SW_OPEN_SILENT | SW_OPEN_READ_ONLY, "", 0, 0)),
    ("OpenDoc3", lambda: app.OpenDoc3(PATH, SW_DOC_PART, 0, 0)),
    ("ActiveDoc fallback", lambda: app.ActiveDoc),
]

working_strategy = None
for label, fn in strategies:
    try:
        doc = fn()
        status = f"OK -> {type(doc).__name__}" if doc else "returned None"
        print(f"  {label:20s}: {status}")
        if doc and working_strategy is None:
            working_strategy = label
            # Close before trying next strategy
            try:
                app.CloseDoc(PATH)
            except Exception:
                pass
        elif doc is None:
            print(f"  {label:20s}: returned None (file may already be closed)")
    except Exception as e:
        print(f"  {label:20s}: FAILED — {e}")

print(f"\n  Best strategy: {working_strategy or 'NONE — all failed'}")

print()
print("=" * 60)
print("SECTION 5: Full metadata read (end-to-end test)")
print("=" * 60)
print("Opening file, reading properties, closing...")
from tool_metadata import get_file_metadata
result = get_file_metadata(PATH)
pprint.pprint(result)

print()
print("=" * 60)
print("SECTION 6: Connection manager open/close cycle")
print("=" * 60)
try:
    from sw_connection import get_connection
    conn = get_connection()
    doc, err = conn.open_part_silent(PATH)
    print(f"open_part_silent: OK (err={err})")
    try:
        print(f"GetPathName:      {doc.GetPathName()}")
    except Exception as e:
        print(f"GetPathName:      failed ({e})")
    conn.close_doc(PATH)
    print("close_doc:        OK")
except Exception as e:
    print(f"FAILED: {e}")


print()
print("=" * 60)
print("SECTION 7: Mass properties (Tool 2)")
print("=" * 60)
from tool_mass import get_mass_properties
result = get_mass_properties(PATH)
pprint.pprint(result)


print()
print("=" * 60)
print("SECTION 8: Shape comparison (Tool 3)")
print("=" * 60)
from tool_compare import compare_shapes
print("Comparing file against itself (expect score ~1.0)...")
result = compare_shapes(PATH, PATH)
pprint.pprint(result)


print()
print("=" * 60)
print("SECTION 9: Shape comparison against wrong student submission")
print("=" * 60)
STUDENT_PATH = r'C:\Users\gce4\Box\ES-19\Spring 2026\Grading\Section 1\Quiz 3\Problem_1\Kondo.Rachel-Quiz3-1.SLDPRT'
print(f"Solution: {PATH}")
print(f"Student:  {STUDENT_PATH}")
print()
result = compare_shapes(STUDENT_PATH, PATH)
pprint.pprint(result)


print()
print("=" * 60)
print("SECTION 10: Sketch status (Tool 4)")
print("=" * 60)
from tool_sketch import check_sketch_status
result = check_sketch_status(PATH)
pprint.pprint(result)


print()
print("=" * 60)
print("SECTION 10: Sketch status (Tool 4)")
print("=" * 60)
from tool_sketch import check_sketch_status
result = check_sketch_status(PATH)
print(f"Method: {result['method']}")
print(f"Underdefined: {result['underdefined_count']}")
pprint.pprint(result)

JENNY = r'C:\Users\gce4\Box\ES-19\Spring 2026\Grading\Section 1\Quiz 3\Problem_1\Chen.Jenny-Quiz3-1.SLDPRT'
print()
print("Checking Chen.Jenny (expect Sketch4 underdefined)...")
result2 = check_sketch_status(JENNY)
print(f"Underdefined: {result2['underdefined_sketch_names']}")
pprint.pprint(result2['all_sketches'])

print()
print("=" * 60)
print("All sections complete.")
print("=" * 60)
