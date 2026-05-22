"""
Canvas SpeedGrader Credit Clicker  (Script 3 of 3)
===================================================
Run AFTER canvas_reorganizer.py has produced submission_map.json.

What this script does:
  1. Reads submission_map.json to know which problems each student submitted.
  2. Opens SpeedGrader in Chrome — you log in and navigate to the first student.
  3. For each student, enters the submission iframe and clicks the credit button
     for each problem the student actually submitted (skips unsubmitted ones).
  4. Pauses after each student so you can verify before moving on.
  5. Supports manual navigation (N) to jump to any student, and quit (Q) early.
  6. Prints a full summary at the end showing what was clicked and what was skipped.
"""

import os
import re
import json
import time
import traceback
from datetime import datetime
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

LOG_PATH = None  # set after config

def log(msg: str):
    print(msg)
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def safe_input(prompt: str, default: Optional[str] = None) -> str:
    val = input(prompt).strip()
    if val == "" and default is not None:
        return default
    return val


def normalize_name(name: str) -> str:
    """Lowercase, strip extra whitespace — for fuzzy matching canvas names to JSON keys."""
    return re.sub(r"\s+", " ", name.strip().lower())


def find_submission_map_key(canvas_name: str, submission_map: dict) -> Optional[str]:
    """
    Match the Canvas display name to a key in the submission_map.
    Tries exact match first, then normalized match, then last-name partial match.
    Returns the matching key or None.
    """
    # Exact match
    if canvas_name in submission_map:
        return canvas_name

    # Normalized match
    norm_canvas = normalize_name(canvas_name)
    for key in submission_map:
        if normalize_name(key) == norm_canvas:
            return key

    # Folder-name style match: submission_map keys may be "Last.First"
    # Canvas names are "First Last" or "Last, First" — try matching last name
    canvas_parts = re.sub(r",", "", canvas_name).split()
    for key in submission_map:
        key_parts = re.sub(r"[._,]", " ", key).split()
        # Check if all canvas name parts appear somewhere in the key
        if all(any(cp.lower() == kp.lower() for kp in key_parts) for cp in canvas_parts):
            return key

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

print("\nCanvas SpeedGrader Credit Clicker\n")

ASSIGNMENT_FOLDER = safe_input(
    "Enter the assignment folder path (same one used in downloader/reorganizer)\n> "
).strip().strip('"')

# Load submission map
json_path = os.path.join(ASSIGNMENT_FOLDER, "submission_map.json")
if not os.path.exists(json_path):
    print(f"\nERROR: submission_map.json not found at:\n  {json_path}")
    print("Run canvas_reorganizer.py first to generate this file.")
    input("\nPress ENTER to exit.")
    raise SystemExit

with open(json_path, "r", encoding="utf-8") as jf:
    submission_map: dict = json.load(jf)

print(f"\nLoaded submission map: {len(submission_map)} students.")

while True:
    try:
        NUM_PROBLEMS = int(safe_input("How many problems/parts? [default: 16]\n> ", "16"))
        if NUM_PROBLEMS > 0:
            break
    except ValueError:
        pass
    print("Please enter a whole number > 0.")

while True:
    try:
        MAX_STUDENTS = int(safe_input(
            "Maximum number of students to process (0 = all)\n> ", "0"
        ))
        if MAX_STUDENTS >= 0:
            break
    except ValueError:
        pass
    print("Please enter 0 or a positive number.")

# Button selector — the CSS class from the inspected element
# Canvas generates long repeated class strings; we match on the base class name.
BUTTON_SELECTOR = safe_input(
    "\nEnter the CSS class name to identify the credit button\n"
    "(e.g. 'css-173i0w7-view--inlineBlock-baseButton' — just ONE of the repeated classes)\n"
    "[default: css-173i0w7-view--inlineBlock-baseButton]\n> ",
    "css-173i0w7-view--inlineBlock-baseButton"
).strip().lstrip(".")

# Log file
LOG_PATH = os.path.join(
    ASSIGNMENT_FOLDER,
    f"clicker_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
)
log(f"Log started: {datetime.now().isoformat(timespec='seconds')}")
log(f"ASSIGNMENT_FOLDER={ASSIGNMENT_FOLDER}")
log(f"NUM_PROBLEMS={NUM_PROBLEMS}  MAX_STUDENTS={MAX_STUDENTS}")
log(f"BUTTON_SELECTOR=.{BUTTON_SELECTOR}")
log(f"Submission map loaded: {len(submission_map)} students")


# ─────────────────────────────────────────────────────────────────────────────
# Selenium setup
# ─────────────────────────────────────────────────────────────────────────────

options = webdriver.ChromeOptions()
options.add_argument("--disable-popup-blocking")
options.add_argument("--no-default-browser-check")
options.add_argument("--window-position=0,0")
options.add_argument("--window-size=1280,900")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_argument("--disable-notifications")

driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, 25)

# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

try:
    driver.get("https://canvas.tufts.edu")
    input(
        "\n1) Log in to Canvas\n"
        "2) Open the assignment in SpeedGrader\n"
        "3) Navigate to the FIRST student\n"
        "Then press ENTER here to begin...\n"
    )

    driver.switch_to.window(driver.window_handles[-1])

    log("Waiting for SpeedGrader UI...")
    wait.until(EC.presence_of_element_located((By.ID, "next-student-button")))
    log("SpeedGrader detected. Starting loop.")

    processed_students = set()
    student_counter = 0

    # Summary tracking: { canvas_name: {"clicked": [1,3,5], "skipped": [2,4], "not_found": [6]} }
    report: dict = {}

    while True:
        if MAX_STUDENTS and student_counter >= MAX_STUDENTS:
            log("\nReached max student limit. Stopping.")
            break

        student_name = "(unknown)"
        try:
            # Read current student name
            student_name_elem = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='selected-student'] span span")
                )
            )
            student_name = student_name_elem.text.strip() or "(unknown)"

            if student_name in processed_students:
                log("\nReached a student already processed. Stopping.")
                break

            processed_students.add(student_name)
            student_counter += 1
            log(f"\n[{student_counter}] Student: {student_name}")

            # Look up which problems this student submitted
            map_key = find_submission_map_key(student_name, submission_map)
            if map_key:
                submitted_problems = set(submission_map[map_key])
                log(f"  Submission map match: '{map_key}' — submitted problems: {sorted(submitted_problems)}")
            else:
                submitted_problems = None
                log(f"  WARNING: '{student_name}' not found in submission_map.json — will attempt all {NUM_PROBLEMS} buttons.")

            # Enter submission iframe
            submission_iframe = wait.until(
                EC.presence_of_element_located((By.ID, "submission-preview-iframe"))
            )
            driver.switch_to.frame(submission_iframe)
            time.sleep(0.7)

            # Find all credit buttons
            buttons = driver.find_elements(By.CSS_SELECTOR, f".{BUTTON_SELECTOR}")
            log(f"  Found {len(buttons)} button(s) matching selector.")

            if not buttons:
                log("  WARNING: No buttons found. The CSS class may have changed — check the selector.")

            clicked = []
            skipped = []
            not_found = []

            for btn_idx in range(1, NUM_PROBLEMS + 1):
                # Decide whether to click based on submission map
                if submitted_problems is not None and btn_idx not in submitted_problems:
                    log(f"  - Problem {btn_idx:>2}: SKIP (not in submission map)")
                    skipped.append(btn_idx)
                    continue

                # Try to get the button at this index (1-based)
                if btn_idx > len(buttons):
                    log(f"  - Problem {btn_idx:>2}: NOT FOUND (only {len(buttons)} buttons in iframe)")
                    not_found.append(btn_idx)
                    continue

                btn = buttons[btn_idx - 1]
                try:
                    # Scroll into view then click
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                    time.sleep(0.15)
                    btn.click()
                    log(f"  - Problem {btn_idx:>2}: CLICKED")
                    clicked.append(btn_idx)
                    time.sleep(0.2)  # brief pause between clicks
                except Exception as btn_err:
                    log(f"  - Problem {btn_idx:>2}: ERROR clicking — {repr(btn_err)}")
                    not_found.append(btn_idx)

            report[student_name] = {
                "clicked": clicked,
                "skipped": skipped,
                "not_found": not_found,
            }

            driver.switch_to.default_content()

            # ── Pause after each student ──────────────────────────────────
            print(f"\n{'─'*60}")
            print(f"  Finished: {student_name}")
            print(f"  Clicked : {clicked}")
            print(f"  Skipped : {skipped}  (no submission)")
            if not_found:
                print(f"  Missing : {not_found}  (button not found in iframe)")
            print(f"{'─'*60}")
            print(f"  Options:")
            print(f"    ENTER       Advance to next student automatically")
            print(f"    N           Manually navigate to a specific student in")
            print(f"                Canvas, then press ENTER here to continue")
            print(f"    Q           Quit and show summary")
            pause_choice = input("  Choice [ENTER / N / Q]: ").strip().upper()

            if pause_choice == "Q":
                log("User quit after completing student.")
                break

            if pause_choice == "N":
                print("\n  Navigate to the student you want in SpeedGrader now.")
                print("  When you are on the correct student, press ENTER here.")
                input("  Ready > ")
                log("User manually navigated to a new student.")
                continue

            # ENTER — click next student button
            next_button = wait.until(
                EC.presence_of_element_located((By.ID, "next-student-button"))
            )
            cls = (next_button.get_attribute("class") or "").lower()
            if "disabled" in cls:
                log("\nReached last student. Finished!")
                break

            next_button.click()

            # Wait for student name to actually change
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: (
                        d.find_element(
                            By.CSS_SELECTOR, "[data-testid='selected-student'] span span"
                        ).text.strip() not in (student_name, "")
                    )
                )
            except Exception:
                time.sleep(1.5)

        except Exception as e:
            log(f"\nFATAL error on student {student_name}: {repr(e)}")
            log(traceback.format_exc())
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            break

finally:
    try:
        driver.quit()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Final summary report
# ─────────────────────────────────────────────────────────────────────────────

SEP = "═" * 68
print(f"\n{SEP}")
print(f"  CLICKER SUMMARY  —  {len(report)} students processed")
print(SEP)

all_not_found = []

for sname, data in report.items():
    clicked  = data["clicked"]
    skipped  = data["skipped"]
    nf       = data["not_found"]
    status = "✓" if not nf else f"✗ {len(nf)} button(s) not found"
    print(f"\n  {sname}  [{status}]")
    if clicked:
        print(f"    Clicked : {clicked}")
    if skipped:
        print(f"    Skipped : {skipped}  (no submission)")
    if nf:
        print(f"    Missing : {nf}  ← check manually")
        all_not_found.append((sname, nf))

print(f"\n{SEP}")
if all_not_found:
    print(f"  NEEDS MANUAL REVIEW ({len(all_not_found)} student(s)):")
    for sname, nf in all_not_found:
        print(f"    {sname}  —  Problems {nf}")
else:
    print("  All buttons clicked successfully.")
print(f"{SEP}\n")

log(SEP)
log(f"CLICKER SUMMARY: {len(report)} students")
for sname, nf in all_not_found:
    log(f"  NEEDS REVIEW: {sname} problems {nf}")
log(SEP)

input("\nPress ENTER to close... (log saved in assignment folder)\n")
