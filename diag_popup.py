"""
diag_popup.py
-------------
Run this, then open a .sldprt file in SolidWorks manually.
When the "educational version" popup appears, this script will
print its exact window title and button text so we can target it.
"""
import time
import pythoncom
pythoncom.CoInitialize()

from pywinauto import Desktop

print("Watching for SW dialogs for 15 seconds...")
print("Open a .sldprt file in SolidWorks NOW to trigger the popup.\n")

seen = set()
deadline = time.time() + 15

while time.time() < deadline:
    try:
        for win in Desktop(backend="win32").windows():
            try:
                title = win.window_text()
                class_name = win.class_name()
                
                # Only show windows we haven't seen yet
                key = (title, class_name)
                if key not in seen and title:
                    seen.add(key)
                    print(f"Window found:")
                    print(f"  Title:      '{title}'")
                    print(f"  Class:      '{class_name}'")
                    
                    # Try to list child buttons
                    try:
                        children = win.children()
                        buttons = [c for c in children if 'button' in c.class_name().lower() or 'button' in str(c.friendly_class_name()).lower()]
                        if buttons:
                            print(f"  Buttons:    {[b.window_text() for b in buttons]}")
                    except Exception:
                        pass
                    print()
            except Exception:
                pass
    except Exception:
        pass
    time.sleep(0.2)

print("Done watching.")
