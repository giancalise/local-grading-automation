"""
diag_crash.py
-------------
Test crash recovery and connection resilience.
Run this if SW is behaving strangely.
"""
import pythoncom
pythoncom.CoInitialize()
import pprint
from sw_connection import (
    solidworks_health_check, get_connection,
    close_all_docs, recover_from_stall, reset_connection
)
from popup_dismisser import ensure_dismisser_running

print("=== 1. SW health check ===")
pprint.pprint(solidworks_health_check())

print("\n=== 2. Close all open documents ===")
ensure_dismisser_running()
closed = close_all_docs()
print(f"  Closed {closed} documents")

print("\n=== 3. Connection liveness check ===")
try:
    conn = get_connection()
    print(f"  Connected: {conn.application.RevisionNumber}")
except Exception as e:
    print(f"  Connection failed: {e}")

print("\n=== 4. Stall recovery test ===")
recovered = recover_from_stall(timeout_s=5.0)
print(f"  Recovery result: {'OK' if recovered else 'FAILED — restart SW'}")

print("\n=== 5. Force fresh connection ===")
reset_connection()
try:
    conn = get_connection()
    print(f"  Fresh connection: {conn.application.RevisionNumber}")
except Exception as e:
    print(f"  Fresh connection failed: {e}")

print("\nDone. If SW is still stalled, close and reopen SolidWorks manually.")
