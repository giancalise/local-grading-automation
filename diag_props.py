"""
diag_props.py
-------------
Probe all SummaryInfo indices and custom property methods on an open doc.
Run with 0253.SLDPRT already open in SW, OR let it open it.
"""
import pythoncom
pythoncom.CoInitialize()

import win32com.client
from popup_dismisser import ensure_dismisser_running
from sw_connection import get_connection

PATH = r'C:\Users\gce4\Box\ES-19\CADFiles\Listed\0253.SLDPRT'

ensure_dismisser_running()
conn = get_connection()
doc, _ = conn.open_part_silent(PATH)

print("=== SummaryInfo indices 0-20 ===")
for i in range(21):
    try:
        val = doc.SummaryInfo(i)
        if val and str(val).strip():
            print(f"  [{i}] = {repr(val)}")
    except Exception as e:
        print(f"  [{i}] error: {e}")

print("\n=== GetPathName as property vs method ===")
try:
    val = doc.GetPathName
    print(f"  As property: {repr(val)}")
except Exception as e:
    print(f"  As property failed: {e}")
try:
    val = doc.GetPathName()
    print(f"  As method: {repr(val)}")
except Exception as e:
    print(f"  As method failed: {e}")

print("\n=== Custom property approaches ===")

# Approach A: Extension.CustomPropertyManager
print("  A) Extension.CustomPropertyManager:")
try:
    ext = doc.Extension
    print(f"     Extension: {ext}")
    mgr = ext.CustomPropertyManager("")
    print(f"     Manager: {mgr}")
    if mgr:
        names = mgr.GetNames()
        print(f"     Names: {names}")
except Exception as e:
    print(f"     Failed: {e}")

# Approach B: IPartDoc custom properties
print("  B) GetCustomInfoNames / GetCustomInfoValues:")
try:
    names = doc.GetCustomInfoNames()
    print(f"     Names: {names}")
    if names:
        for name in names:
            val = doc.GetCustomInfo2(name, 0)
            print(f"     {name} = {val}")
except Exception as e:
    print(f"     Failed: {e}")

# Approach C: CustomProperty directly on doc
print("  C) CustomProperty method:")
try:
    val = doc.CustomProperty("Description")
    print(f"     Description = {repr(val)}")
except Exception as e:
    print(f"     Failed: {e}")

# Approach D: GetCustomInfo
print("  D) GetCustomInfo:")
try:
    val = doc.GetCustomInfo("Description")
    print(f"     Description = {repr(val)}")
except Exception as e:
    print(f"     Failed: {e}")

conn.close_doc(PATH)
print("\nDone.")
