import os
import re
import time
import shutil
import traceback
from datetime import datetime
from typing import Optional, Set, Tuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# -----------------------------
# Logging
# -----------------------------
def log(msg: str):
    print(msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


# -----------------------------
# Helpers
# -----------------------------
def safe_input(prompt: str, default: Optional[str] = None) -> str:
    val = input(prompt).strip()
    if val == "" and default is not None:
        return default
    return val


def parse_student_name(student_name: str) -> Tuple[str, str]:
    """
    Returns (last, first) from common Canvas display formats:
      - "First Last"
      - "Last, First"
      - "First Middle Last"
    """
    s = student_name.strip()
    if not s:
        return ("Unknown", "Student")

    if "," in s:
        last, rest = s.split(",", 1)
        last = last.strip() or "Unknown"
        first = rest.strip().split()[0] if rest.strip() else "Student"
        return (last, first)

    parts = s.split()
    if len(parts) == 1:
        return (parts[0], "Student")

    first = parts[0]
    last = parts[-1]
    return (last, first)


def student_label(student_name: str) -> str:
    last, first = parse_student_name(student_name)

    def clean(x: str) -> str:
        return re.sub(r"[^A-Za-z0-9\-']+", "", x)

    last = clean(last) or "Unknown"
    first = clean(first) or "Student"
    return f"{last}.{first}"


def snapshot_dir(temp_dir: str) -> Set[str]:
    try:
        return set(os.listdir(temp_dir))
    except Exception:
        return set()


def file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return -1


def wait_until_file_stable(path: str, stable_seconds: float = 2.0, timeout_s: int = 30) -> bool:
    """
    Waits until:
      - file exists
      - size stops changing for stable_seconds
      - file is not a .crdownload (Chrome partial download)
      - file is readable
    """
    deadline = time.time() + timeout_s
    last_size = file_size(path)
    last_change = time.time()

    while time.time() < deadline:
        # Reject .crdownload partials
        if path.lower().endswith(".crdownload"):
            time.sleep(0.25)
            continue

        if not os.path.exists(path):
            time.sleep(0.25)
            continue

        cur_size = file_size(path)
        if cur_size != last_size:
            last_size = cur_size
            last_change = time.time()

        readable = True
        try:
            with open(path, "rb") as _:
                pass
        except Exception:
            readable = False

        if readable and (time.time() - last_change) >= stable_seconds and cur_size > 0:
            return True

        time.sleep(0.25)

    return False


def wait_for_new_download(temp_dir: str, before: Set[str], timeout_s: int = 60) -> Optional[str]:
    """
    Wait until a new, fully-finished file appears in temp_dir.
    - Ignores *.crdownload
    - Ignores suspicious 'temp' / no-extension placeholders
    - Waits for the file size to stabilize before returning
    """
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        current = snapshot_dir(temp_dir)

        # New candidates excluding Chrome in-progress extensions
        candidates = [
            f for f in (current - before)
            if not f.lower().endswith(".crdownload")
            and not f.lower().endswith(".tmp")
        ]

        if candidates:
            # pick newest by mtime
            newest = max(candidates, key=lambda fn: os.path.getmtime(os.path.join(temp_dir, fn)))
            full = os.path.join(temp_dir, newest)

            base = os.path.basename(full)
            ext = os.path.splitext(base)[1].lower()

            # Treat no-extension files as suspicious placeholders
            if base.lower() in ("temp", "download", "file") or ext == "":
                time.sleep(0.5)
                continue

            # Ensure it is stable (finished writing)
            if wait_until_file_stable(full, stable_seconds=2.0, timeout_s=min(30, max(5, int(timeout_s)))):
                return full

        time.sleep(0.5)

    return None


def find_file_elements(driver):
    """
    Try multiple CSS selectors to find downloadable file links in Canvas.
    Canvas uses generated class names that can change between versions.
    Returns a list of elements (may be empty).
    """
    # List of selectors to try, in order of preference
    selectors = [
        "span.css-1vgnq4w-text",          # Original selector (older Canvas)
        "a[data-testid='file-link']",      # Canvas LTI file links
        "a.instructure_file_link",         # Common Canvas file link class
        "a[href*='/files/']",              # Any link pointing to /files/
        "span[class*='-text'] a",          # Span with 'text' in class containing a link
        "div.ef-item-row a.ef-name-col__link",  # Canvas file browser links
        "a[download]",                     # Any anchor with download attribute
    ]

    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                return elements, selector
        except Exception:
            continue

    return [], None


def click_file_link(file_elem, driver):
    """Try normal click on parent, then JS click fallback."""
    try:
        parent = file_elem.find_element(By.XPATH, "..")
        parent.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", file_elem)
            return True
        except Exception:
            return False


def pick_new_downloads(temp_dir: str, before: Set[str]) -> list:
    """
    Return all new, stable, completed files in temp_dir since `before` snapshot.
    Does NOT delete anything — caller decides what to do with multiples.
    """
    current = snapshot_dir(temp_dir)
    candidates = [
        f for f in (current - before)
        if not f.lower().endswith(".crdownload")
        and not f.lower().endswith(".tmp")
        and os.path.splitext(f)[1] != ""
        and f.lower() not in ("temp", "download", "file")
    ]
    full_paths = [os.path.join(temp_dir, f) for f in candidates]
    full_paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return full_paths


def click_with_retry(file_elem, driver, temp_dir: str, timeout_s: int = 90) -> Optional[str]:
    """
    Fires TWO clicks (preview-click then download-click) with a short gap.
    Renames the downloaded file immediately to a unique temp name so subsequent
    downloads for other students/problems never collide in the temp folder.
    Returns the path of the renamed temp file, or None if nothing arrived.
    """
    before = snapshot_dir(temp_dir)

    # First click (opens preview or triggers download)
    click_file_link(file_elem, driver)
    time.sleep(0.6)
    # Second click (triggers download if first only opened preview)
    click_file_link(file_elem, driver)

    downloaded = wait_for_new_download(temp_dir, before, timeout_s=timeout_s)
    if not downloaded:
        return None

    # Short extra wait in case the double-click produced a second file
    time.sleep(1.5)

    candidates = pick_new_downloads(temp_dir, before)
    if not candidates:
        return None

    # Use the most recently modified file; if there are extras, leave them —
    # they will be picked up as the "before" snapshot has already been taken
    # for this slot, so they won't pollute the next file's download window.
    chosen = candidates[0]

    # Rename immediately to a unique staging name so it can never be confused
    # with a future download for a different student/problem.
    ext = os.path.splitext(chosen)[1]
    staged = os.path.join(temp_dir, f"_staged_{int(time.time()*1000)}{ext}")
    try:
        os.rename(chosen, staged)
        return staged
    except Exception:
        return chosen  # if rename fails, return original path


# -----------------------------
# Prompts / Configuration
# -----------------------------
DEFAULT_ROOT = r"C:\TempGrading"
DEFAULT_TEMP = r"C:\TempDownloads"

print("\nCanvas SpeedGrader Submission Downloader\n")
print("NOTE: Requires Python + Selenium 4.6+. Install with: pip install selenium")
print("ChromeDriver is managed automatically — no manual download needed.\n")

ASSIGNMENT_FOLDER = safe_input(
    f"Enter full path where PROBLEM folders should be saved (this should be the assignment folder)\n"
    f"[default: {DEFAULT_ROOT}]\n> ",
    DEFAULT_ROOT,
).strip('"')

TEMP_DOWNLOAD_DIR = safe_input(
    f"Enter temp download folder for Chrome\n[default: {DEFAULT_TEMP}]\n> ",
    DEFAULT_TEMP,
).strip('"')

ASSIGNMENT_LABEL = safe_input(
    "Enter assignment label to embed in filenames (e.g., Module5, Module_5, Quiz3)\n"
    "(blank = use assignment folder name)\n> "
).strip()

if not ASSIGNMENT_LABEL:
    ASSIGNMENT_LABEL = os.path.basename(os.path.abspath(ASSIGNMENT_FOLDER)).replace(" ", "")

while True:
    try:
        num_str = safe_input("How many problem folders / files per student? [default: 16]\n> ", "16")
        NUM_PROBLEMS = int(num_str)
        if NUM_PROBLEMS <= 0:
            raise ValueError
        break
    except ValueError:
        print("Please enter a whole number > 0.")

# Script 1 only collects files into per-student folders.
# Problem-folder routing is handled by the separate reorganizer script.
FILE_NUMBER_START = None  # routing disabled in this script

while True:
    try:
        max_students_str = safe_input("Maximum number of students to process (0 = until last student/repeat)\n> ", "0")
        MAX_STUDENTS = int(max_students_str)
        if MAX_STUDENTS < 0:
            raise ValueError
        break
    except ValueError:
        print("Please enter 0 or a whole number >= 0.")

# Prepare base folders (student subfolders created on the fly)
os.makedirs(ASSIGNMENT_FOLDER, exist_ok=True)
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

# Log file
LOG_PATH = os.path.join(ASSIGNMENT_FOLDER, f"scraper_log_{ASSIGNMENT_LABEL}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
log(f"Log started: {datetime.now().isoformat(timespec='seconds')}")
log(f"ASSIGNMENT_FOLDER={ASSIGNMENT_FOLDER}")
log(f"TEMP_DOWNLOAD_DIR={TEMP_DOWNLOAD_DIR}")
log(f"ASSIGNMENT_LABEL={ASSIGNMENT_LABEL}")
log(f"NUM_PROBLEMS={NUM_PROBLEMS}  MAX_STUDENTS={MAX_STUDENTS}")

# -----------------------------
# Selenium setup
# NOTE: selenium-manager (Selenium 4.6+) auto-downloads the correct ChromeDriver.
# No manual chromedriver.exe installation needed.
# -----------------------------
options = webdriver.ChromeOptions()
prefs = {
    "download.default_directory": TEMP_DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True,
}
options.add_experimental_option("prefs", prefs)
# Keep Chrome from stealing focus / popping over other windows.
# We do NOT use --headless because Canvas SpeedGrader requires a visible
# session for login and iframe interactions, but these flags keep it
# from jumping to the foreground during downloads.
options.add_argument("--disable-popup-blocking")
options.add_argument("--no-default-browser-check")
options.add_argument("--window-position=0,0")
options.add_argument("--window-size=1280,900")
# Prevent download-complete notifications from stealing focus
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_argument("--disable-notifications")

driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, 25)

try:
    driver.get("https://canvas.tufts.edu")
    input(
        "\n1) Log in to Canvas\n2) Open the assignment in SpeedGrader\n3) Navigate to the FIRST student\n"
        "Then press ENTER here to begin...\n"
    )

    # Switch to the most recently active window (Canvas may have opened new tabs during login)
    driver.switch_to.window(driver.window_handles[-1])

    # Wait for SpeedGrader UI
    log("Waiting for SpeedGrader student UI...")
    wait.until(EC.presence_of_element_located((By.ID, "next-student-button")))
    log("SpeedGrader detected. Starting loop.")

    processed_students = set()
    student_counter = 0
    # report_data: { student_name: { problem_num: filename | "MISSING" } }
    # report_data: { student_name: [list of saved filenames] }
    report_data: dict = {}

    while True:
        if MAX_STUDENTS and student_counter >= MAX_STUDENTS:
            log("\nReached max student limit. Stopping.")
            break

        student_name = "(unknown)"
        try:
            student_name_elem = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='selected-student'] span span"))
            )
            student_name = student_name_elem.text.strip() or "(unknown)"

            if student_name in processed_students:
                log("\nReached a student already processed. Stopping.")
                break

            processed_students.add(student_name)
            student_counter += 1

            s_label = student_label(student_name)
            log(f"\n[{student_counter}] Student: {student_name}  ->  {s_label}")
            report_data[student_name] = []

            # Switch to submission iframe
            submission_iframe = wait.until(EC.presence_of_element_located((By.ID, "submission-preview-iframe")))
            driver.switch_to.frame(submission_iframe)
            time.sleep(0.7)

            # Find file elements using multiple selector fallbacks
            file_elements, matched_selector = find_file_elements(driver)
            log(f"  Found {len(file_elements)} file link(s) via selector: {matched_selector}")

            if not file_elements:
                log("  WARNING: No file links found for this student. They may not have submitted.")

            # Attempt downloads
            for idx, file_elem in enumerate(file_elements[:NUM_PROBLEMS]):
                try:
                    displayed_name = (file_elem.text or "").strip() or f"(file {idx+1})"
                    log(f"  - File {idx+1}: attempting download ({displayed_name})")

                    downloaded_path = click_with_retry(file_elem, driver, TEMP_DOWNLOAD_DIR, timeout_s=90)

                    # ── Failsafe: manual intervention prompt ──────────────
                    if not downloaded_path or not os.path.exists(downloaded_path):
                        log(f"    ! Auto-download failed for file {idx+1} ({displayed_name}).")
                        driver.switch_to.default_content()
                        print(f"\n*** MANUAL INTERVENTION NEEDED ***")
                        print(f"    Student : {student_name}")
                        print(f"    File    : {displayed_name}")
                        print(f"    Options :")
                        print(f"      R - Retry automated click")
                        print(f"      M - I will manually download it now (place in {TEMP_DOWNLOAD_DIR})")
                        print(f"      S - Skip this file")
                        choice = input("    Choice [R/M/S]: ").strip().upper()

                        if choice == "R":
                            driver.switch_to.frame(
                                driver.find_element(By.ID, "submission-preview-iframe")
                            )
                            downloaded_path = click_with_retry(file_elem, driver, TEMP_DOWNLOAD_DIR, timeout_s=90)
                            if not downloaded_path or not os.path.exists(downloaded_path):
                                log("    ! Retry also failed. Skipping.")
                                driver.switch_to.default_content()
                                driver.switch_to.frame(
                                    driver.find_element(By.ID, "submission-preview-iframe")
                                )
                                continue
                        elif choice == "M":
                            before_manual = snapshot_dir(TEMP_DOWNLOAD_DIR)
                            input(f"    Download the file manually into {TEMP_DOWNLOAD_DIR}, then press ENTER...")
                            downloaded_path = wait_for_new_download(TEMP_DOWNLOAD_DIR, before_manual, timeout_s=30)
                            if not downloaded_path or not os.path.exists(downloaded_path):
                                log("    ! No file found after manual download. Skipping.")
                                driver.switch_to.frame(
                                    driver.find_element(By.ID, "submission-preview-iframe")
                                )
                                continue
                            log(f"    Manual download accepted: {os.path.basename(downloaded_path)}")
                        else:
                            log(f"    Skipped by user.")
                            driver.switch_to.frame(
                                driver.find_element(By.ID, "submission-preview-iframe")
                            )
                            continue

                        # Re-enter iframe after manual intervention
                        try:
                            driver.switch_to.frame(
                                driver.find_element(By.ID, "submission-preview-iframe")
                            )
                        except Exception:
                            pass

                    # ── Save into student folder, preserving original filename ──
                    raw_basename = os.path.splitext(os.path.basename(downloaded_path))[0]
                    # Strip staging prefix to recover original name
                    clean_basename = re.sub(r"^_staged_\d+_?", "", raw_basename)
                    ext = os.path.splitext(downloaded_path)[1]

                    student_folder = os.path.join(ASSIGNMENT_FOLDER, s_label)
                    os.makedirs(student_folder, exist_ok=True)

                    # Include student label prefix + original filename for easy identification
                    original_name = clean_basename if clean_basename else f"file_{idx+1}"
                    new_filename = f"{s_label}-{original_name}{ext}"
                    dest_path = os.path.join(student_folder, new_filename)

                    # Avoid overwriting if two files share an identical name
                    if os.path.exists(dest_path):
                        base, e = os.path.splitext(new_filename)
                        dest_path = os.path.join(student_folder, f"{base}_dup{e}")

                    shutil.move(downloaded_path, dest_path)
                    log(f"    Saved: {os.path.basename(dest_path)} -> {s_label}/")
                    report_data[student_name].append(os.path.basename(dest_path))

                except Exception as file_err:
                    log("    ! ERROR while downloading/moving this file:")
                    log("    " + repr(file_err))
                    log("    " + traceback.format_exc().replace("\n", "\n    "))
                    continue

            driver.switch_to.default_content()

            # Next student — wait until the name actually changes rather than a fixed sleep
            next_button = wait.until(EC.presence_of_element_located((By.ID, "next-student-button")))
            cls = (next_button.get_attribute("class") or "").lower()
            if "disabled" in cls:
                log("\nReached last student. Finished!")
                break

            next_button.click()

            # Wait for student name to change (up to 10s) before looping
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: (
                        d.find_element(By.CSS_SELECTOR, "[data-testid='selected-student'] span span").text.strip()
                        not in (student_name, "")
                    )
                )
            except Exception:
                time.sleep(1.5)  # fallback if wait times out

        except Exception as e:
            log(f"\nFATAL error processing student {student_name}: {repr(e)}")
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

log("\nDone.")

# ─────────────────────────────────────────────
# End-of-run summary report
# ─────────────────────────────────────────────
SEP = "-" * 72
print("\n" + SEP)
print(f"  DOWNLOAD SUMMARY  —  {ASSIGNMENT_LABEL}")
print(f"  {len(report_data)} students processed")
print(SEP)

short_students: list = []  # students with fewer files than expected

for sname, files in report_data.items():
    count = len(files)
    status = f"✓ {count} file(s)" if count >= NUM_PROBLEMS else f"~ {count}/{NUM_PROBLEMS} files (check manually)"
    if count < NUM_PROBLEMS:
        short_students.append((sname, count))
    print(f"\n  {sname}  [{status}]")
    for fn in files:
        print(f"    {fn}")
    if not files:
        print(f"    (no files downloaded)")

print("\n" + SEP)
if short_students:
    print(f"  STUDENTS WITH FEWER THAN {NUM_PROBLEMS} FILES:")
    for sname, count in short_students:
        print(f"    {sname}  —  {count} file(s) downloaded")
    print(f"\n  NOTE: Run the reorganizer script after manually reviewing student folders.")
else:
    print(f"  All students have {NUM_PROBLEMS} files. Ready for reorganizer script.")
print(SEP + "\n")

log(SEP)
log(f"SUMMARY: {len(report_data)} students processed")
for sname, count in short_students:
    log(f"  SHORT: {sname} only {count}/{NUM_PROBLEMS} files")
log(SEP)

input("\nPress ENTER to close... (log saved in assignment folder)\n")
