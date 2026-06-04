# Modification of Grading Agent to run locally for demonstration

# Imports
import os
import sys
import json
import time
import logging
import tempfile
import shutil
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Configuration
SCRIPT_DIR = Path(r"C:\Users\Austin\Documents\Code\Sample")
SERVICE_ACCOUNT_PATH = SCRIPT_DIR / "firebase-service-account.json"
LOG_FILE = SCRIPT_DIR / "grading_agent.log"
SOLUTION_DIR = SCRIPT_DIR / "solutions"

STORAGE_BUCKET = "gen-lang-client-0024774658.firebasestorage.app"
FIRESTORE_DATABASE_ID = "ai-studio-c398f7e7-ad91-4bb2-8229-ade228c29c66"
JOBS_COLLECTION = "grading_jobs"
RESULTS_COLLECTION = "grading_results"

POLL_INTERVAL_SECONDS = 10
MAX_BACKOFF_SECONDS = 120


# Functions
def run_single_grade(job: dict, local_students: Path,
                     local_solution: Path, local_output: Path,
                     student_identity_map: dict | None = None):
    sys.path.insert(0, str(SCRIPT_DIR))
    from grade_assignment import grade_assignment
    grade_assignment(
        students_folder=str(local_students),
        solution_path=str(local_solution),
        output_folder=str(local_output),
        assignment_name=job["assignmentId"],
        student_identity_map=student_identity_map or {},
    )


def run_multi_grade(job: dict, local_students: Path,
                    local_solutions: Path, local_output: Path):
    sys.path.insert(0, str(SCRIPT_DIR))
    from grade_midterm import grade_midterm
    grade_midterm(
        students_folder=str(local_students),
        solutions_folder=str(local_solutions),
        output_folder=str(local_output),
        assignment=job["assignmentId"],
    )

def process_job(job: dict):
    """ job = {
    "assignmentId"  :"1",
    "assignmentName":"Homework",
    "assignmentType":"single"} """
    assignment_id = job["assignmentId"]
    assignment_name = job.get("assignmentName", assignment_id)
    assignment_type = job.get("assignmentType", "single")
    #result_base = job["resultStoragePath"].rstrip("/")

    # Create a temp working directory
    tmp_root = Path(tempfile.mkdtemp(prefix=f"grading_test_"))

    try:
        local_students = SCRIPT_DIR / "students"
        local_solutions = SCRIPT_DIR / "solutions"
        local_output = SCRIPT_DIR / "output"
        local_output.mkdir(parents=True, exist_ok=True)

        # ── FLATTEN STUDENT FILES + BUILD IDENTITY MAP ───────────────────────
        # Downloads land in students/{uid}/filename.SLDPRT
        # grade_assignment expects all .SLDPRT files directly in the folder.
        # We also build filename→{uid, display_name} so grades use Firebase names.
        local_students_flat = tmp_root / "students_flat"
        local_students_flat.mkdir(parents=True, exist_ok=True)

        # filename → {uid, display_name}
        student_identity_map: dict = {}

        for sldprt in local_students.rglob("*.SLDPRT"):
            uid = sldprt.parent.name   # folder name IS the Firebase UID
            dest = local_students_flat / sldprt.name
            if not dest.exists():
                import shutil as _shutil
                _shutil.copy2(sldprt, dest)
            # Fetch name from file downloaded
            # Fetch display name from Firebase Auth
            display_name = None
            """ try:
                from firebase_admin import auth as fb_auth
                user = fb_auth.get_user(uid)
                display_name = user.display_name or user.email or uid
            except Exception as e:
                display_name = uid """
            student_identity_map[sldprt.name] = {
                "uid": uid,
                "display_name": display_name,
            }

        n_flat = len(list(local_students_flat.glob("*.SLDPRT")))

        # ── RUN GRADING ───────────────────────────────────────────────────────
        try:
            if assignment_type == "single":
                local_solution_file = SOLUTION_DIR / "cswa1101.sldprt"
                run_single_grade(job, local_students_flat, local_solution_file, local_output, student_identity_map)
            else:
                run_multi_grade(job, local_students, local_solutions, local_output)
        except ImportError as e:
            raise RuntimeError(
                f"Grading script not found or import error: {e}. "
                f"Make sure grade_assignment.py / grade_midterm.py exist in {SCRIPT_DIR}"
            )
        except Exception as e:
            msg = str(e).lower()
            if "solidworks" in msg or "dispatch" in msg or "com_error" in msg:
                raise RuntimeError(
                    "SolidWorks is not running or not accessible. "
                    "Please open SolidWorks and try again."
                )
            raise

        # ── LOCATE OUTPUT FILES ───────────────────────────────────────────────
        json_file = local_output / f"{assignment_id}_grades.json"
        csv_file  = local_output / f"{assignment_id}_grades.csv"
        stl_dir   = local_output / "stl" / assignment_id  # or wherever scripts write STLs

        # Fallback: search output folder for the JSON if path differs
        if not json_file.exists():
            candidates = list(local_output.rglob("*_grades.json"))
            if candidates:
                json_file = candidates[0]

    finally:
        # Always clean up temp dir
        try:
            shutil.rmtree(tmp_root, ignore_errors=True)
        except Exception:
            pass


process_job({
    "assignmentId"  :"1",
    "assignmentName":"Homework",
    "assignmentType":"single"})

""" def main():

    backoff = POLL_INTERVAL_SECONDS

    while True:
        try:
            db, bucket = init_firebase()
            backoff = POLL_INTERVAL_SECONDS  # reset on successful connection

            pending = fetch_pending_jobs(db)

            if not pending:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Process jobs one at a time
            for job_ref, job in pending:
                try:
                    process_job(db, bucket, job_ref, job)
                except Exception as exc:
                    err_msg = str(exc)

            # Immediately check for more jobs before sleeping
            continue

        except KeyboardInterrupt:
            sys.exit(0)

        except Exception as exc:
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS) """