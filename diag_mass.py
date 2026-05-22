"""
diag_mass.py - round 2
Probe GetMassProperties as property, and material access.
"""
import pythoncom
pythoncom.CoInitialize()

from popup_dismisser import ensure_dismisser_running
from sw_connection import get_connection

PATH = r'C:\Users\gce4\Box\ES-19\CADFiles\Listed\0253.SLDPRT'

ensure_dismisser_running()
conn = get_connection()
doc, _ = conn.open_part_silent(PATH)

print("=== GetMassProperties as property ===")
try:
    props = doc.GetMassProperties
    print(f"  Raw value: {repr(props)}")
    print(f"  Type: {type(props)}")
    if props:
        print(f"  Length: {len(props)}")
        for i, v in enumerate(props):
            print(f"  [{i}] = {v}")
except Exception as e:
    print(f"  Failed: {e}")

print("\n=== GetMassProperties2 as property ===")
try:
    props = doc.GetMassProperties2
    print(f"  Raw: {repr(props)}")
except Exception as e:
    print(f"  Failed: {e}")

print("\n=== Material via MaterialIdName ===")
try:
    mat = doc.MaterialIdName
    print(f"  MaterialIdName: {repr(mat)}")
except Exception as e:
    print(f"  Failed: {e}")

print("\n=== GetMaterialPropertyName2 as property ===")
try:
    mat = doc.GetMaterialPropertyName2
    print(f"  As property: {repr(mat)}")
except Exception as e:
    print(f"  Failed: {e}")

print("\n=== Try calling GetMassProperties with rebuild first ===")
try:
    doc.ForceRebuild3(False)
    print("  ForceRebuild3: OK")
except Exception as e:
    print(f"  ForceRebuild3: {e}")
try:
    props = doc.GetMassProperties
    print(f"  After rebuild: {repr(props)}")
except Exception as e:
    print(f"  Failed: {e}")

conn.close_doc(PATH)
print("\nDone.")
