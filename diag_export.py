"""
diag_export.py
--------------
Probe STL export API availability on SW 2026 Student Edition.
Run with 0253.SLDPRT closed in SW.
"""
import pythoncom
pythoncom.CoInitialize()

import os
import tempfile
from popup_dismisser import ensure_dismisser_running
from sw_connection import get_connection

PATH = r'C:\Users\gce4\Box\ES-19\CADFiles\Listed\0253.SLDPRT'
OUT  = os.path.join(tempfile.gettempdir(), 'sw_test_export.stl')

ensure_dismisser_running()
conn = get_connection()
doc, _ = conn.open_part_silent(PATH)

print(f"Export target: {OUT}")

# Approach A: SaveAs with STL extension
print("\n=== Approach A: SaveAs (STL extension) ===")
try:
    result = doc.SaveAs(OUT)
    print(f"  SaveAs result: {result}")
    if os.path.exists(OUT):
        print(f"  File created: {os.path.getsize(OUT)} bytes")
        os.remove(OUT)
    else:
        print("  File NOT created")
except Exception as e:
    print(f"  Failed: {e}")

# Approach B: SaveAs3 with format flags
print("\n=== Approach B: SaveAs3 ===")
try:
    # swSaveAsOptions_Silent = 1, swSaveAsCurrentVersion = 1
    result = doc.SaveAs3(OUT, 0, 1)
    print(f"  SaveAs3 result: {result}")
    if os.path.exists(OUT):
        print(f"  File created: {os.path.getsize(OUT)} bytes")
        os.remove(OUT)
except Exception as e:
    print(f"  Failed: {e}")

# Approach C: Extension.SaveAs
print("\n=== Approach C: Extension.SaveAs ===")
try:
    ext = doc.Extension
    # swSaveAsFormat_STL = 26
    result = ext.SaveAs(OUT, 0, 1, None, 0, 0)
    print(f"  Extension.SaveAs result: {result}")
    if os.path.exists(OUT):
        print(f"  File created: {os.path.getsize(OUT)} bytes")
        os.remove(OUT)
except Exception as e:
    print(f"  Failed: {e}")

# Approach D: SaveAs as property
print("\n=== Approach D: SaveAs as property ===")
try:
    val = doc.SaveAs
    print(f"  Type: {type(val)}")
except Exception as e:
    print(f"  Failed: {e}")

conn.close_doc(PATH)
print("\nDone.")
