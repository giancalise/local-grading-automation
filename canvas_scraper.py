"""
canvas_scraper_v9.py
--------------------
Canvas SpeedGrader submission downloader with dual folder organization.

For each student, downloads all submitted files in order and assigns them
to problems by position (file 1 → Problem 1, file 2 → Problem 2, etc.).

Output structure
----------------
<root>/
  by_student/
    Kondo_Rachel/
      Problem_1/
        Kondo_Rachel_Quiz3_Problem1.SLDPRT
      Problem_2/
        Kondo_Rachel_Quiz3_Problem2.SLDPRT
      ...
  by_problem/
    Problem_1/
      Kondo_Rachel_Quiz3_Problem1.SLDPRT
      Chen_Jenny_Quiz3_Problem1.SLDPRT
      ...

Edge cases
----------
- Student submits 2 files for one slot  → first renamed to _a, second is _b
- Student skips a problem               → slot left empty, warning printed
- Student submits more than NUM_PROBLEMS → extras go into Problem_extra/

Usage
-----
  python canvas_scraper_v9.py
  1. Fill in the prompts
  2. Log into Canvas in the opened Chrome window
  3. Open the assignment in SpeedGrader, navigate to the FIRST student
  4. Press ENTER in the terminal to begin
"""

import os
import re
import time
import shutil
from typing import Optional, Set

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions  (all defined before main logic)
# ─────────────────────────────────────────────────────────────────────────────

def safe_input(prompt: str, default: Optional[str] = None) -> str:
    """Prompt with optional default. Blank input returns default."""
    val = input(prompt).strip()
    if val == "" and default is not None:
        return default
    return val


def parse_student_name(canvas_name: str) -> tuple:
    """
    Parse Canvas display name into (last, first).

    Handles:
      "Rachel Kondo"    → ('Kondo', 'Rachel')
      "Kondo, Rachel"   → ('Kondo', 'Rachel')
      "Rachel A. Kondo" → ('Kondo', 'Rachel')  (middle initial stripped)
    """
    name = canvas_name.strip()

    # "Last, First" format
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        last  = parts[0]
        first = parts[1].split()[0] if parts[1].strip() else "Unknown"
        return last, first

    # "First [Middle...] Last" format
    parts = name.split()
    if not parts:
        return "Unknown", "Unknown"
    if len(parts) == 1:
        return parts[0], "Unknown"

    first = parts[0]
    last  = parts[-1]
    return last, first


def make_student_key(canvas_name: str) -> str:
    """Return filesystem-safe 'Last_First' string from Canvas display name."""
    last, first = parse_student_name(canvas_name)
    last  = re.sub(r"[^\w]", "", last)
    first = re.sub(r"[^\w]", "", first)
    return f"{last}_{first}"


def wait_for_new_download(temp_dir: str, before: Set[str],
                          timeout_s: int = 60) -> Optional[str]:
    """
    Wait until a new fully-downloaded file appears in temp_dir.
    Ignores .crdownload / .tmp partial files.
    Returns full path or None on timeout.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            current = set(os.listdir(temp_dir))
        except FileNotFoundError:
            return None

        new_files = [
            f for f in (current - before)
            if not f.endswith(".crdownload") and not f.endswith(".tmp")
        ]
        if new_files:
            newest = max(
                new_files,
                key=lambda fn: os.path.getmtime(os.path.join(temp_dir, fn)),
            )
            time.sleep(0.3)   # ensure file is fully flushed
            return os.path.join(temp_dir, newest)

        time.sleep(0.4)
    return None


def rename_first_in_slot(student_problem_dir: str, by_problem_dir: str,
                          filename_base: str, ext: str) -> None:
    """
    When a second file arrives for the same problem slot, retroactively
    rename the first copy to _a in both folder trees.

      LastName_First_Assign_Problem1.SLDPRT → ..._Problem1_a.SLDPRT
    """
    old_name = f"{filename_base}{ext}"
    new_name = f"{filename_base}_a{ext}"

    for folder in [student_problem_dir, by_problem_dir]:
        old_path = os.path.join(folder, old_name)
        new_path = os.path.join(folder, new_name)
        if os.path.exists(old_path):
            try:
                os.rename(old_path, new_path)
            except Exception as e:
                print(f"    ! Could not rename {old_name}: {e}")


def place_file(src_path: str,
               student_problem_dir: str,
               by_problem_dir: str,
               filename_base: str,
               suffix: str = "") -> None:
    """
    Copy src_path into both folder trees with the canonical filename.
    Creates destination directories if they do not exist.
    """
    ext   = os.path.splitext(src_path)[1]
    final = f"{filename_base}{suffix}{ext}"

    for dest_dir in [student_problem_dir, by_problem_dir]:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src_path, os.path.join(dest_dir, final))


# ─────────────────────────────────────────────────────────────────────────────
# Startup prompts
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("  Canvas SpeedGrader Downloader  v9")
print("=" * 60 + "\n")

ASSIGNMENT_NAME = (
    safe_input("Assignment name (used in filenames, e.g. 'Quiz3', 'Midterm')\n> ")
    or "Assignment"
)

while True:
    try:
        NUM_PROBLEMS = int(
            safe_input("Number of problems in this assignment [default: 9]\n> ", "9")
        )
        if NUM_PROBLEMS > 0:
            break
        print("Must be at least 1.")
    except ValueError:
        print("Please enter a whole number.")

while True:
    try:
        MAX_FILES_PER_STUDENT = int(
            safe_input("Max files to download per student (safety cap) [default: 20]\n> ", "20")
        )
        if MAX_FILES_PER_STUDENT > 0:
            break
        print("Must be at least 1.")
    except ValueError:
        print("Please enter a whole number.")

while True:
    try:
        MAX_STUDENTS = int(
            safe_input("Max students to process (0 = all students)\n> ", "0")
        )
        if MAX_STUDENTS >= 0:
            break
        print("Must be 0 or greater.")
    except ValueError:
        print("Please enter 0 or a whole number.")

DEFAULT_ROOT = r"C:\TempGrading"
ROOT_FOLDER = safe_input(
    f"\nRoot output folder — by_student/ and by_problem/ will be created here\n"
    f"[default: {DEFAULT_ROOT}]\n> ",
    DEFAULT_ROOT,
)

DEFAULT_TEMP = r"C:\TempDownloads"
TEMP_DOWNLOAD_DIR = safe_input(
    f"\nTemp Chrome download folder (separate from output)\n"
    f"[default: {DEFAULT_TEMP}]\n> ",
    DEFAULT_TEMP,
)

# ── Derived paths ─────────────────────────────────────────────────────────────
BY_STUDENT_ROOT = os.path.join(ROOT_FOLDER, "by_student")
BY_PROBLEM_ROOT = os.path.join(ROOT_FOLDER, "by_problem")

for d in [ROOT_FOLDER, BY_STUDENT_ROOT, BY_PROBLEM_ROOT, TEMP_DOWNLOAD_DIR]:
    os.makedirs(d, exist_ok=True)

# Pre-create all by_problem subdirectories
for n in range(1, NUM_PROBLEMS + 1):
    os.makedirs(os.path.join(BY_PROBLEM_ROOT, f"Problem_{n}"), exist_ok=True)
os.makedirs(os.path.join(BY_PROBLEM_ROOT, "Problem_extra"), exist_ok=True)

print(f"\n  Assignment  : {ASSIGNMENT_NAME}  ({NUM_PROBLEMS} problems)")
print(f"  by_student  : {BY_STUDENT_ROOT}")
print(f"  by_problem  : {BY_PROBLEM_ROOT}")
print(f"  Temp dir    : {TEMP_DOWNLOAD_DIR}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Selenium setup
# ─────────────────────────────────────────────────────────────────────────────

options = webdriver.ChromeOptions()
prefs = {
    "download.default_directory": TEMP_DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True,
}
options.add_experimental_option("prefs", prefs)
options.add_argument("--start-maximized")

driver = webdriver.Chrome(options=options)
wait   = WebDriverWait(driver, 20)

# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

processed_students: Set[str] = set()
student_counter = 0
warning_log: list = []

# Suffix sequence for duplicate files in the same slot:
#   1st file → no suffix  (if a 2nd arrives, 1st is retroactively renamed to _a)
#   2nd file → _b, 3rd → _c, etc.
_SUFFIXES = ["", "_b", "_c", "_d", "_e", "_f"]


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

try:
    driver.get("https://canvas.tufts.edu")
    input(
        "\n  Before pressing ENTER:\n"
        "    1. Log in to Canvas\n"
        "    2. Open the assignment in SpeedGrader\n"
        "    3. Navigate to the FIRST student\n"
        "  → Press ENTER to begin...\n"
    )
    driver.switch_to.window(driver.window_handles[-1])

    while True:

        # ── Student limit ────────────────────────────────────────────────────
        if MAX_STUDENTS and student_counter >= MAX_STUDENTS:
            print(f"\nReached max student limit ({MAX_STUDENTS}). Stopping.")
            break

        student_name = "(unknown)"

        try:
            # ── Read student name from SpeedGrader ───────────────────────────
            name_elem = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='selected-student'] span span")
                )
            )
            student_name = name_elem.text.strip()

            if student_name in processed_students:
                print(f"\nCircled back to '{student_name}' — all students processed.")
                break

            processed_students.add(student_name)
            student_counter += 1
            student_key = make_student_key(student_name)

            print(f"\n{'─' * 50}")
            print(f"[{student_counter}] {student_name}  →  {student_key}")

            # ── Enter submission iframe ──────────────────────────────────────
            iframe = wait.until(
                EC.presence_of_element_located((By.ID, "submission-preview-iframe"))
            )
            driver.switch_to.frame(iframe)
            time.sleep(1.0)

            # ── Find downloadable file links ─────────────────────────────────
            file_elements = driver.find_elements(By.CSS_SELECTOR, "span.css-1vgnq4w-text")

            if not file_elements:
                msg = f"WARNING: No files found for {student_name}"
                print(f"  ⚠  {msg}")
                warning_log.append(msg)
                driver.switch_to.default_content()

            else:
                n_found = len(file_elements)
                n_to_dl = min(n_found, MAX_FILES_PER_STUDENT)
                print(f"  Found {n_found} file(s). Downloading {n_to_dl}.")

                if n_found > NUM_PROBLEMS:
                    msg = (
                        f"WARNING: {student_name} uploaded {n_found} files "
                        f"({NUM_PROBLEMS} expected) — extras → Problem_extra/"
                    )
                    print(f"  ⚠  {msg}")
                    warning_log.append(msg)

                student_base_dir = os.path.join(BY_STUDENT_ROOT, student_key)

                # slot_counts[problem_label] = # files placed in that slot so far
                slot_counts: dict = {}

                for idx in range(n_to_dl):

                    # Re-fetch element list each iteration to avoid stale refs
                    try:
                        elems = driver.find_elements(
                            By.CSS_SELECTOR, "span.css-1vgnq4w-text"
                        )
                        if idx >= len(elems):
                            print(f"  [{idx+1}] Element gone from DOM — skipping.")
                            continue
                        elem      = elems[idx]
                        displayed = elem.text.strip() or f"file_{idx+1}"
                    except Exception as e:
                        print(f"  [{idx+1}] Could not read element: {e}")
                        continue

                    print(f"  [{idx+1}/{n_to_dl}] {displayed}")

                    before = set(os.listdir(TEMP_DOWNLOAD_DIR))

                    try:
                        elem.find_element(By.XPATH, "..").click()
                    except Exception as e:
                        print(f"    ! Click failed: {e}")
                        continue

                    dl_path = wait_for_new_download(TEMP_DOWNLOAD_DIR, before, timeout_s=60)
                    if not dl_path or not os.path.exists(dl_path):
                        print("    ! Download timed out — skipping.")
                        continue

                    print(f"    ✓ {os.path.basename(dl_path)}")

                    # ── Assign to problem slot by position (1-based) ─────────
                    problem_num = idx + 1

                    if problem_num <= NUM_PROBLEMS:
                        problem_label = f"Problem_{problem_num}"
                        filename_base = (
                            f"{student_key}_{ASSIGNMENT_NAME}_Problem{problem_num}"
                        )
                    else:
                        problem_label = "Problem_extra"
                        filename_base = (
                            f"{student_key}_{ASSIGNMENT_NAME}_Extra{problem_num}"
                        )

                    ext                      = os.path.splitext(dl_path)[1]
                    slot_counts[problem_label] = slot_counts.get(problem_label, 0) + 1
                    count                    = slot_counts[problem_label]

                    student_problem_dir = os.path.join(student_base_dir, problem_label)
                    by_problem_dir      = os.path.join(BY_PROBLEM_ROOT,  problem_label)

                    # If this is the 2nd file in the slot, retroactively rename
                    # the already-placed first file to _a
                    if count == 2:
                        rename_first_in_slot(
                            student_problem_dir,
                            by_problem_dir,
                            filename_base,
                            ext,
                        )

                    suffix = (
                        _SUFFIXES[count - 1]
                        if count <= len(_SUFFIXES)
                        else f"_{count}"
                    )

                    place_file(
                        dl_path,
                        student_problem_dir,
                        by_problem_dir,
                        filename_base,
                        suffix=suffix,
                    )

                    # Remove temp copy
                    try:
                        os.remove(dl_path)
                    except Exception:
                        pass

                    print(f"    → {problem_label}/{filename_base}{suffix}{ext}")

                # ── Warn about missing problem slots ─────────────────────────
                for p in range(1, NUM_PROBLEMS + 1):
                    label = f"Problem_{p}"
                    if slot_counts.get(label, 0) == 0:
                        msg = f"WARNING: {student_name} — no submission for Problem {p}"
                        print(f"  ⚠  {msg}")
                        warning_log.append(msg)

                driver.switch_to.default_content()

            # ── Advance to next student ──────────────────────────────────────
            try:
                next_btn = wait.until(
                    EC.presence_of_element_located((By.ID, "next-student-button"))
                )
                disabled = (
                    "disabled" in (next_btn.get_attribute("class") or "").lower()
                    or next_btn.get_attribute("disabled") is not None
                )
                if disabled:
                    print("\nReached last student. Finished!")
                    break
                next_btn.click()
                time.sleep(1.5)
            except Exception as nav_err:
                print(f"\nNavigation error: {nav_err}. Stopping.")
                break

        except Exception as outer_err:
            print(f"\nUnexpected error on '{student_name}': {outer_err}")
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            # Attempt to advance before giving up
            try:
                driver.find_element(By.ID, "next-student-button").click()
                time.sleep(1.5)
            except Exception:
                print("Could not advance to next student. Stopping.")
                break

finally:
    try:
        driver.quit()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Final summary
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print(f"  Done.  Processed {student_counter} student(s).")
print("=" * 60)

if warning_log:
    print(f"\n  ⚠  {len(warning_log)} warning(s):")
    for w in warning_log:
        print(f"    • {w}")
else:
    print("\n  No warnings — clean run!")

print(f"\n  Output root  : {ROOT_FOLDER}")
print(f"    by_student/ : one folder per student, subfolders per problem")
print(f"    by_problem/ : one folder per problem, all students inside")
print(f"\n  Next step → pass by_problem/ folders to grade_midterm.py")
print()
