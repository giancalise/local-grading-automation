"""
Canvas Submission Reorganizer  (Script 2 of 2)
===============================================
Run AFTER canvas_downloader.py has collected all files into per-student folders
and you have manually verified the submissions look correct.

What this script does:
  1. Scans every student subfolder inside the assignment folder.
  2. For each student, lists their files and tries to auto-detect which
     problem number each file belongs to using flexible pattern matching:
       - 4-digit codes like 2301, 2302 ... (offset from a base you provide)
       - Short codes like MT1, MT2, P1, P2, Q1, HW3 ...
       - Plain numbers like 1, 2, 03 ...
  3. Shows you a proposed mapping and lets you confirm, adjust, or skip.
  4. Moves approved files into Problem_N subfolders with standardised names.
  5. Prints a final summary of what landed where and what is still missing.
"""

import os
import re
import shutil
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def safe_input(prompt: str, default: Optional[str] = None) -> str:
    val = input(prompt).strip()
    if val == "" and default is not None:
        return default
    return val


def list_student_folders(assignment_folder: str) -> list:
    """Return sorted list of immediate subdirectories that look like student folders."""
    entries = []
    for name in sorted(os.listdir(assignment_folder)):
        full = os.path.join(assignment_folder, name)
        if os.path.isdir(full) and not name.startswith("Problem_") and not name.startswith("_") and name != "Problems":
            entries.append((name, full))
    return entries


def list_files(folder: str) -> list:
    """Return sorted list of files (not dirs) inside folder."""
    return sorted(
        f for f in os.listdir(folder)
        if os.path.isfile(os.path.join(folder, f)) and not f.startswith(".")
    )


def strip_chrome_duplicate_suffix(stem: str) -> str:
    """
    Chrome appends ' (1)', ' (2)' etc. when a filename already exists.
    e.g. '2301 (1)' -> '2301', 'MT3 (2)' -> 'MT3'
    Strip these before pattern matching so they don't confuse number detection.
    Also flags whether the file is a suspected Chrome duplicate.
    """
    cleaned = re.sub(r"\s*\(\d+\)\s*$", "", stem).strip()
    is_duplicate = cleaned != stem.strip()
    return cleaned, is_duplicate


def guess_problem_number(filename: str,
                          num_problems: int,
                          base_code: Optional[int],
                          prefix_pattern: Optional[str]) -> tuple:
    """
    Try multiple strategies to extract a problem number from a filename.
    Returns (problem_num_or_None, is_chrome_duplicate).

    Strategies tried in order:
      1. 4-digit base code      e.g. 2305        -> Problem 5
      2. User-supplied prefix   e.g. MT3, HW7    -> Problem 3/7
      3. Common prefix patterns e.g. P5, Part2   -> Problem 5/2
      4. file_N pattern         e.g. file_6      -> Problem 6  (our downloader fallback name)
      5. Trailing number        e.g. Name-6      -> Problem 6
      6. Any standalone number  last resort
    """
    raw_stem = os.path.splitext(filename)[0]
    stem, is_dupe = strip_chrome_duplicate_suffix(raw_stem)

    # Strategy 1: 4-digit offset code (e.g. 2305 -> Problem 5)
    if base_code is not None:
        for m in re.findall(r"\d{4}", stem):
            offset = int(m) - base_code
            if 0 <= offset < num_problems:
                return offset + 1, is_dupe

    # Strategy 2: user-supplied prefix (e.g. "MT" -> MT1, MT2 ...)
    if prefix_pattern:
        pat = re.compile(rf"(?i){re.escape(prefix_pattern)}[\s_-]?(\d+)")
        m = pat.search(stem)
        if m:
            n = int(m.group(1))
            if 1 <= n <= num_problems:
                return n, is_dupe

    # Strategy 3: common short prefix patterns
    m = re.search(r"(?i)(?:MT|part|prob(?:lem)?|HW|Q|P)[\s_-]?(\d+)", stem)
    if m:
        n = int(m.group(1))
        if 1 <= n <= num_problems:
            return n, is_dupe

    # Strategy 4: file_N pattern — produced by the downloader when no better
    # name was available (e.g. "Wang.Kelly-file_6")
    m = re.search(r"(?i)file[_\s-]?(\d+)", stem)
    if m:
        n = int(m.group(1))
        if 1 <= n <= num_problems:
            return n, is_dupe

    # Strategy 5: number immediately after the last hyphen or underscore
    # e.g. "SomeName-6" or "thing_12"
    m = re.search(r"[-_](\d{1,2})$", stem)
    if m:
        n = int(m.group(1))
        if 1 <= n <= num_problems:
            return n, is_dupe

    # Strategy 6: any isolated number (last resort)
    for ns in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", stem):
        n = int(ns)
        if 1 <= n <= num_problems:
            return n, is_dupe

    return None, is_dupe


def build_dest_path(problems_folder: str, s_label: str,
                    assignment_label: str, problem_num: int,
                    ext: str) -> str:
    """Return a unique destination path inside Problems/Problem_N, appending _dup if needed."""
    problem_folder = os.path.join(problems_folder, f"Problem_{problem_num}")
    filename = f"{s_label}-{assignment_label}-{problem_num}{ext}"
    dest = os.path.join(problem_folder, filename)
    if os.path.exists(dest):
        base, e = os.path.splitext(filename)
        dest = os.path.join(problem_folder, f"{base}_dup{e}")
    return dest


# ─────────────────────────────────────────────────────────────────────────────
# Configuration prompts
# ─────────────────────────────────────────────────────────────────────────────

print("\nCanvas Submission Reorganizer\n")
print("This script moves files from per-student folders into Problem_N folders.")
print("You will review and confirm each student's mapping before anything is moved.\n")

ASSIGNMENT_FOLDER = safe_input(
    "Enter the assignment folder path (same one used in the downloader)\n> "
).strip().strip('"')

ASSIGNMENT_LABEL = safe_input(
    "Enter the assignment label used in filenames (e.g. Midterm2026)\n> "
).strip()

while True:
    try:
        NUM_PROBLEMS = int(safe_input("How many problems/parts? [default: 16]\n> ", "16"))
        if NUM_PROBLEMS > 0:
            break
    except ValueError:
        pass
    print("Please enter a whole number > 0.")

BASE_CODE_STR = safe_input(
    "\nEnter 4-digit base code if files use numbered convention (e.g. '2301')\n"
    "Leave blank to skip this matching strategy\n> "
).strip()
BASE_CODE = int(BASE_CODE_STR) if BASE_CODE_STR.isdigit() else None

PREFIX_PATTERN = safe_input(
    "Enter filename prefix to match (e.g. 'MT' for MT1, MT2 ... or 'P' for P1, P2)\n"
    "Leave blank to skip\n> "
).strip()

# ─────────────────────────────────────────────────────────────────────────────
# Pre-create Problems/Problem_N folder structure
# ─────────────────────────────────────────────────────────────────────────────

PROBLEMS_FOLDER = os.path.join(ASSIGNMENT_FOLDER, "Problems")
os.makedirs(PROBLEMS_FOLDER, exist_ok=True)
for k in range(1, NUM_PROBLEMS + 1):
    os.makedirs(os.path.join(PROBLEMS_FOLDER, f"Problem_{k}"), exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Main loop — one student at a time
# ─────────────────────────────────────────────────────────────────────────────

student_folders = list_student_folders(ASSIGNMENT_FOLDER)
if not student_folders:
    print(f"\nNo student folders found in:\n  {ASSIGNMENT_FOLDER}")
    print("Make sure you ran the downloader first and the path is correct.")
    input("\nPress ENTER to exit.")
    raise SystemExit

SEP = "─" * 68

# Track results for final report
# { student_folder_name: { problem_num: filename } }
report: dict = {}
skipped_students: list = []

for folder_name, folder_path in student_folders:
    files = list_files(folder_path)
    if not files:
        print(f"\n{SEP}")
        print(f"  {folder_name}  (no files — skipping)")
        skipped_students.append(folder_name)
        continue

    # ── Auto-detect problem numbers ───────────────────────────────────────
    mapping: dict = {}   # { filename: guessed_problem_num or None }
    # mapping: { filename: (guessed_problem_num_or_None, is_chrome_dupe) }
    mapping: dict = {}
    for fn in files:
        pnum, is_dupe = guess_problem_number(fn, NUM_PROBLEMS, BASE_CODE, PREFIX_PATTERN or None)
        mapping[fn] = (pnum, is_dupe)

    print(f"\n{SEP}")
    print(f"  Student: {folder_name}")
    print(f"  Files found: {len(files)}\n")

    # Display proposed mapping — flag Chrome duplicates clearly
    for i, fn in enumerate(files):
        pnum, is_dupe = mapping[fn]
        if pnum:
            guess_str = f"Problem_{pnum}"
            if is_dupe:
                guess_str += "  ⚠ Chrome duplicate suffix stripped — verify this is correct"
        else:
            guess_str = "??? (no match — will need manual assignment)"
        print(f"  [{i+1:>2}]  {fn}")
        print(f"        -> {guess_str}")

    # ── Interactive confirmation / correction ─────────────────────────────
    print()
    print("  Options:")
    print("    ENTER       Accept all auto-detected mappings above")
    print("    C           Correct one or more mappings manually")
    print("    S           Skip this student entirely (do not move files)")
    print()

    while True:
        choice = safe_input("  Choice [ENTER / C / S]: ", "").upper()

        if choice == "S":
            print(f"  Skipped {folder_name}.")
            skipped_students.append(folder_name)
            mapping = {}
            break

        elif choice == "C":
            print("\n  Enter corrections. For each file number, type:")
            print("  '1=5' to assign file 1 to Problem 5, or '1=skip' to skip that file.")
            print("  Press ENTER with no input when done.\n")
            while True:
                correction = safe_input("  Correction (blank to finish): ", "").strip()
                if correction == "":
                    break
                try:
                    left, right = correction.split("=", 1)
                    file_idx = int(left.strip()) - 1
                    fn = files[file_idx]
                    _, existing_dupe_flag = mapping[fn]
                    if right.strip().lower() == "skip":
                        mapping[fn] = (None, existing_dupe_flag)
                        print(f"    File {file_idx+1} ({fn}) -> SKIP")
                    else:
                        pnum = int(right.strip())
                        if 1 <= pnum <= NUM_PROBLEMS:
                            mapping[fn] = (pnum, existing_dupe_flag)
                            print(f"    File {file_idx+1} ({fn}) -> Problem_{pnum}")
                        else:
                            print(f"    ! Problem number must be 1–{NUM_PROBLEMS}")
                except (ValueError, IndexError):
                    print("    ! Invalid format. Use '1=5' or '1=skip'.")

            # Show updated mapping
            print("\n  Updated mapping:")
            for i, fn in enumerate(files):
                pnum, is_dupe = mapping[fn]
                guess_str = f"Problem_{pnum}" if pnum else "SKIP"
                if is_dupe and pnum:
                    guess_str += "  (Chrome dup suffix)"
                print(f"  [{i+1:>2}]  {fn}  ->  {guess_str}")
            print()
            confirm = safe_input("  Accept this mapping? [Y/N]: ", "Y").upper()
            if confirm == "Y":
                break
            # else loop back to let them correct again

        else:
            # ENTER / anything else = accept
            break

    if choice == "S" or not any(pnum for pnum, _ in mapping.values()):
        if choice != "S":
            pass  # mapping may still have files to move
    if not mapping:
        continue  # student was skipped

    # ── Move files ────────────────────────────────────────────────────────
    report[folder_name] = {}
    moved_count = 0
    skipped_dupes = 0

    # Track which problem slots have already been filled for this student
    # so we can detect when a Chrome-duplicate would land in an already-filled slot
    filled_slots: dict = {}  # { problem_num: dest_filename }

    for fn, (pnum, is_dupe) in mapping.items():
        if pnum is None:
            print(f"  SKIP        {fn}")
            continue

        src_path = os.path.join(folder_path, fn)
        ext = os.path.splitext(fn)[1]

        # If this problem slot is already filled AND this file is a suspected
        # Chrome duplicate, skip it automatically rather than saving a _dup copy
        if pnum in filled_slots and is_dupe:
            print(f"  SKIP (dupe) {fn}  — Problem_{pnum} already filled by {filled_slots[pnum]}")
            skipped_dupes += 1
            continue

        dest_path = build_dest_path(PROBLEMS_FOLDER, folder_name, ASSIGNMENT_LABEL, pnum, ext)

        try:
            shutil.copy2(src_path, dest_path)
            dest_basename = os.path.basename(dest_path)
            dupe_note = "  [Chrome dup suffix was present]" if is_dupe else ""
            print(f"  COPIED      {fn}  ->  Problems/Problem_{pnum}/{dest_basename}{dupe_note}")
            report[folder_name][pnum] = dest_basename
            filled_slots[pnum] = dest_basename
            moved_count += 1
        except Exception as e:
            print(f"  ERROR copying {fn}: {e}")

    summary_parts = [f"{moved_count} file(s) copied"]
    if skipped_dupes:
        summary_parts.append(f"{skipped_dupes} Chrome duplicate(s) skipped")
    print(f"\n  Done: {', '.join(summary_parts)} for {folder_name}.")

# ─────────────────────────────────────────────────────────────────────────────
# Final summary report
# ─────────────────────────────────────────────────────────────────────────────

print(f"\n\n{'═' * 68}")
print(f"  FINAL SUMMARY  —  {ASSIGNMENT_LABEL}")
print(f"{'═' * 68}")

all_missing: list = []

for folder_name, problems in report.items():
    missing_nums = [p for p in range(1, NUM_PROBLEMS + 1) if p not in problems]
    status = "✓ Complete" if not missing_nums else f"✗ Missing {len(missing_nums)}"
    print(f"\n  {folder_name}  [{status}]")
    for p in sorted(problems):
        print(f"    Problem {p:>2} : {problems[p]}")
    for p in missing_nums:
        print(f"    Problem {p:>2} : *** NOT SUBMITTED / NOT MOVED ***")
        all_missing.append((folder_name, p))

if skipped_students:
    print(f"\n  SKIPPED STUDENTS ({len(skipped_students)}):")
    for s in skipped_students:
        print(f"    {s}")

print(f"\n{'═' * 68}")
if all_missing:
    print(f"  MISSING FILES ({len(all_missing)} total):")
    for folder_name, p in all_missing:
        print(f"    {folder_name}  —  Problem {p}")
else:
    print("  All problems accounted for across all students.")
print(f"{'═' * 68}\n")

input("Press ENTER to close.\n")
