"""
diag_sketch.py - confirm d7_48 is the status field
Also check Pich.Franklin (Sketch6 underdefined) and Jeong.Stella (Sketch3 underdefined)
Open all files in SW before running.
"""
import pythoncom
pythoncom.CoInitialize()
import win32com.client
from popup_dismisser import ensure_dismisser_running

ensure_dismisser_running()
app = win32com.client.GetActiveObject("SldWorks.Application")

# Ground truth from GraderWorks
EXPECTED_UNDERDEFINED = {
    "0253.SLDPRT": [],
    "Chen.Jenny-Quiz3-1.SLDPRT": ["Sketch4"],
    "Miller.William-Quiz3-1.SLDPRT": ["Sketch1"],
    "Shang.Isaac-Quiz3-1.SLDPRT": ["Sketch2"],
    "Pich.Franklin-Quiz3-1.SLDPRT": ["Sketch6"],
    "Jeong.Stella-Quiz3-1.SLDPRT": ["Sketch3"],
}

# d7_48 value mapping
STATUS_MAP = {
    2: "UNDERDEFINED",
    3: "FULLY_DEFINED",
    1: "OVERDEFINED",   # hypothesis
    0: "NO_SOLUTION",   # hypothesis
}

def get_sketch_status_via_dispid(feat):
    """Get sketch status via DISPID 7 -> DISPID 48."""
    try:
        raw = feat._oleobj_
        obj7 = raw.Invoke(7, 0, 1, 1)
        if obj7 is None:
            return None, None
        w = win32com.client.Dispatch(obj7)
        val = w._oleobj_.Invoke(48, 0, 1, 1)
        return val, STATUS_MAP.get(val, f"UNKNOWN({val})")
    except Exception as e:
        return None, f"ERROR: {e}"

print("=== Validation: d7_48 sketch status across all files ===\n")
correct = 0
total = 0

try:
    docs_var = app.GetDocuments
    if callable(docs_var): docs_var = app.GetDocuments()
    docs = list(docs_var) if docs_var else []
except:
    docs = [app.ActiveDoc] if app.ActiveDoc else []

for doc in docs:
    if not doc: continue
    pn = doc.GetPathName
    if callable(pn): pn = doc.GetPathName()
    fname = pn.split("\\")[-1]
    expected_ud = EXPECTED_UNDERDEFINED.get(fname)
    if expected_ud is None:
        continue

    print(f"FILE: {fname}")
    doc.ForceRebuild3(False)
    fm = doc.FeatureManager
    feats = fm.GetFeatures(False)

    for f in feats:
        try:
            t = f.GetTypeName
            if callable(t): t = f.GetTypeName()
            if t not in ("ProfileFeature", "3DProfileFeature"): continue
            n = f.Name
            if callable(n): n = f.Name()

            val, status = get_sketch_status_via_dispid(f)
            expected_status = "UNDERDEFINED" if n in expected_ud else "FULLY_DEFINED"
            match = "✓" if status == expected_status else "✗ WRONG"
            print(f"  '{n}': d7_48={val} → {status}  [{match}]")

            if val is not None:
                total += 1
                if status == expected_status:
                    correct += 1
        except: pass
    print()

print(f"=== Accuracy: {correct}/{total} correct ===")
if correct == total:
    print("✓ d7_48 perfectly discriminates sketch status!")
    print("  2 = UNDERDEFINED, 3 = FULLY_DEFINED")
else:
    print("✗ Some mismatches — need further investigation")
print("\nDone.")
