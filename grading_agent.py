"""
grading_agent.py
----------------
Local bridge between Firebase and the SolidWorks grading system.
Polls Firestore for pending grading jobs, runs grading scripts,
uploads results back to Firebase Storage and Firestore.

Run with: python grading_agent.py
"""

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

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(r"C:\Users\gce4\Documents\solidworks-mcp")
SERVICE_ACCOUNT_PATH = SCRIPT_DIR / "firebase-service-account.json"
LOG_FILE = SCRIPT_DIR / "grading_agent.log"

STORAGE_BUCKET = "gen-lang-client-0024774658.firebasestorage.app"
FIRESTORE_DATABASE_ID = "ai-studio-c398f7e7-ad91-4bb2-8229-ade228c29c66"
JOBS_COLLECTION = "grading_jobs"
RESULTS_COLLECTION = "grading_results"

POLL_INTERVAL_SECONDS = 10
MAX_BACKOFF_SECONDS = 120

# ── LOGGING SETUP ──────────────────────────────────────────────────────────────

def setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=datefmt,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

log = logging.getLogger(__name__)

# ── FIREBASE INIT ──────────────────────────────────────────────────────────────

def init_firebase():
    import firebase_admin
    from firebase_admin import credentials, firestore, storage

    if not firebase_admin._apps:
        cred = credentials.Certificate(str(SERVICE_ACCOUNT_PATH))
        firebase_admin.initialize_app(cred, {"storageBucket": STORAGE_BUCKET})
        log.info("Firebase Admin SDK initialized.")

    db = firestore.client(database_id=FIRESTORE_DATABASE_ID)
    bucket = storage.bucket()
    return db, bucket

# ── FIRESTORE HELPERS ──────────────────────────────────────────────────────────

def fetch_pending_jobs(db):
    """Return a list of (doc_ref, job_data) for all pending jobs, oldest first."""
    from firebase_admin import firestore as fs
    jobs_ref = db.collection(JOBS_COLLECTION)
    # No order_by — avoids composite index requirement.
    # Agent processes one job at a time so ordering is not critical.
    query = (
        jobs_ref
        .where("status", "==", "pending")
        .limit(5)
    )
    results = []
    for doc in query.stream():
        results.append((doc.reference, doc.to_dict()))
    return results


def mark_running(job_ref):
    from firebase_admin import firestore
    job_ref.update({
        "status": "running",
        "startedAt": firestore.SERVER_TIMESTAMP,
    })


def mark_complete(job_ref, result_json_url, result_csv_url, stl_folder_url):
    from firebase_admin import firestore
    job_ref.update({
        "status": "complete",
        "completedAt": firestore.SERVER_TIMESTAMP,
        "resultJsonUrl": result_json_url,
        "resultCsvUrl": result_csv_url,
        "stlFolderUrl": stl_folder_url,
        "error": None,
    })


def mark_error(job_ref, error_msg):
    from firebase_admin import firestore
    job_ref.update({
        "status": "error",
        "completedAt": firestore.SERVER_TIMESTAMP,
        "error": error_msg,
    })

# ── STORAGE HELPERS ────────────────────────────────────────────────────────────

def download_folder(bucket, storage_prefix: str, local_dir: Path):
    """Download all blobs under storage_prefix into local_dir, preserving structure."""
    local_dir.mkdir(parents=True, exist_ok=True)
    blobs = list(bucket.list_blobs(prefix=storage_prefix))
    if not blobs:
        log.warning(f"No files found at storage path: {storage_prefix}")
    for blob in blobs:
        # Compute relative path from prefix
        rel = blob.name[len(storage_prefix):].lstrip("/")
        if not rel:
            continue  # skip the folder placeholder itself
        dest = local_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        log.info(f"  Downloading: {blob.name} → {dest}")
        blob.download_to_filename(str(dest))
    return blobs


def download_file(bucket, storage_path: str, local_path: Path):
    """Download a single blob to local_path.
    Accepts either a Storage path or a full Firebase Storage URL.
    """
    import re, requests as req
    local_path.parent.mkdir(parents=True, exist_ok=True)
    log.info(f"  Downloading: {storage_path} → {local_path}")

    # If it's a full URL, extract the Storage object path and download directly
    if storage_path.startswith("http"):
        # Try to extract path from Firebase Storage URL for bucket.blob() usage
        # URL format: https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{encoded_path}?...
        m = re.search(r'/o/([^?]+)', storage_path)
        if m:
            from urllib.parse import unquote
            extracted = unquote(m.group(1))
            try:
                blob = bucket.blob(extracted)
                blob.download_to_filename(str(local_path))
                return local_path
            except Exception:
                pass
        # Fallback: download via requests using the URL directly
        resp = req.get(storage_path, timeout=60)
        resp.raise_for_status()
        local_path.write_bytes(resp.content)
        return local_path

    blob = bucket.blob(storage_path)
    blob.download_to_filename(str(local_path))
    return local_path


def upload_file(bucket, local_path: Path, storage_path: str,
                content_type: str = "application/octet-stream") -> str:
    """Upload a file and return its public download URL."""
    blob = bucket.blob(storage_path)
    blob.upload_from_filename(str(local_path), content_type=content_type)
    blob.make_public()
    url = blob.public_url
    log.info(f"  Uploaded: {local_path.name} → {storage_path} ({url})")
    return url


def upload_folder(bucket, local_dir: Path, storage_prefix: str,
                  extensions: tuple = None) -> dict:
    """
    Upload all files from local_dir (recursively) to storage_prefix.
    Returns {relative_path: public_url}.
    """
    urls = {}
    for file in local_dir.rglob("*"):
        if not file.is_file():
            continue
        if extensions and file.suffix.lower() not in extensions:
            continue
        rel = file.relative_to(local_dir).as_posix()
        storage_path = f"{storage_prefix.rstrip('/')}/{rel}"
        ct = "model/stl" if file.suffix.lower() == ".stl" else "application/octet-stream"
        url = upload_file(bucket, file, storage_path, content_type=ct)
        urls[rel] = url
    return urls

# ── GRADING HELPERS ────────────────────────────────────────────────────────────

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


def patch_stl_urls(grades_data: dict, stl_url_map: dict) -> dict:
    """
    Replace local STL paths in grades_data with Firebase Storage public URLs.
    stl_url_map: {filename (e.g. 'solution.stl' or 'username.stl'): url}
    Uses case-insensitive filename matching to handle STL vs stl extension.
    """
    # Build case-insensitive lookup
    stl_url_map_lower = {k.lower(): v for k, v in stl_url_map.items()}

    def lookup(filename: str) -> str | None:
        return stl_url_map_lower.get(filename.lower())

    # Patch solution STL
    if "solution" in grades_data and "stl_path" in grades_data["solution"]:
        sol_filename = Path(grades_data["solution"]["stl_path"]).name
        url = lookup(sol_filename)
        if url:
            grades_data["solution"]["stl_path"] = url

    # Patch each student's STL paths
    for student in grades_data.get("students", []):
        geo = student.get("geometry", {})
        for key in ("student_stl_path", "solution_stl_path"):
            if key in geo:
                filename = Path(geo[key]).name
                url = lookup(filename)
                if url:
                    geo[key] = url
        student["geometry"] = geo

    return grades_data


def write_results_to_firestore(db, assignment_id: str, grades_data: dict):
    """Write the full grading results document to Firestore."""
    doc_ref = db.collection(RESULTS_COLLECTION).document(assignment_id)
    doc_ref.set({"results": grades_data}, merge=True)
    log.info(f"  Results written to Firestore: {RESULTS_COLLECTION}/{assignment_id}")

# ── CORE JOB PROCESSOR ────────────────────────────────────────────────────────

def process_job(db, bucket, job_ref, job: dict):
    assignment_id = job["assignmentId"]
    assignment_name = job.get("assignmentName", assignment_id)
    assignment_type = job.get("assignmentType", "single")
    result_base = job["resultStoragePath"].rstrip("/")

    log.info(f"━━━ Processing job: {assignment_id} ({assignment_type}) ━━━")

    # Create a temp working directory
    tmp_root = Path(tempfile.mkdtemp(prefix=f"grading_{assignment_id}_"))
    log.info(f"  Temp dir: {tmp_root}")

    try:
        local_students = tmp_root / "students"
        local_solutions = tmp_root / "solutions"
        local_output = tmp_root / "output"
        local_output.mkdir(parents=True, exist_ok=True)

        # ── DOWNLOAD INPUTS ───────────────────────────────────────────────────
        log.info("Downloading student submissions...")
        download_folder(bucket, job["submissionsStoragePath"], local_students)

        if assignment_type == "single":
            local_solution_file = tmp_root / "solution.sldprt"
            download_file(bucket, job["solutionStoragePath"], local_solution_file)
        else:
            log.info("Downloading solution files (multi-problem)...")
            download_folder(bucket, job["solutionsStoragePath"], local_solutions)

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
            # Fetch display name from Firebase Auth
            display_name = None
            try:
                from firebase_admin import auth as fb_auth
                user = fb_auth.get_user(uid)
                display_name = user.display_name or user.email or uid
            except Exception as e:
                log.warning(f"  Could not fetch Firebase Auth name for {uid}: {e}")
                display_name = uid
            student_identity_map[sldprt.name] = {
                "uid": uid,
                "display_name": display_name,
            }
            log.info(f"  {uid} → {display_name} ({sldprt.name})")

        n_flat = len(list(local_students_flat.glob("*.SLDPRT")))
        log.info(f"  Flattened {n_flat} student files with identity map")

        # ── RUN GRADING ───────────────────────────────────────────────────────
        log.info(f"Running grading script (type={assignment_type})...")
        try:
            if assignment_type == "single":
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

        log.info("Grading complete. Uploading results...")

        # ── LOCATE OUTPUT FILES ───────────────────────────────────────────────
        json_file = local_output / f"{assignment_id}_grades.json"
        csv_file  = local_output / f"{assignment_id}_grades.csv"
        stl_dir   = local_output / "stl" / assignment_id  # or wherever scripts write STLs

        # Fallback: search output folder for the JSON if path differs
        if not json_file.exists():
            candidates = list(local_output.rglob("*_grades.json"))
            if candidates:
                json_file = candidates[0]
                log.warning(f"  JSON not at expected path; using: {json_file}")

        # ── UPLOAD STL FILES ──────────────────────────────────────────────────
        stl_storage_prefix = f"{result_base}/stl/{assignment_id}"
        stl_url_map = {}

        if stl_dir.exists():
            log.info("Uploading STL files...")
            raw_map = upload_folder(bucket, stl_dir, stl_storage_prefix, extensions=(".stl",))
            # Flatten: basename → url
            stl_url_map = {Path(k).name: v for k, v in raw_map.items()}
        else:
            # Try to find STLs anywhere in output
            for stl_file in local_output.rglob("*.stl"):
                rel_name = stl_file.name
                storage_path = f"{stl_storage_prefix}/{rel_name}"
                url = upload_file(bucket, stl_file, storage_path, content_type="model/stl")
                stl_url_map[rel_name] = url

        stl_folder_url = f"https://storage.googleapis.com/{STORAGE_BUCKET}/{stl_storage_prefix}/"

        # ── UPLOAD JSON ───────────────────────────────────────────────────────
        result_json_url = ""
        if json_file.exists():
            with open(json_file, "r", encoding="utf-8") as f:
                grades_data = json.load(f)

            grades_data = patch_stl_urls(grades_data, stl_url_map)

            # Re-save patched JSON
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(grades_data, f, indent=2)

            storage_json_path = f"{result_base}/{assignment_id}_grades.json"
            result_json_url = upload_file(
                bucket, json_file, storage_json_path, content_type="application/json"
            )

            # Write to Firestore for real-time access
            write_results_to_firestore(db, assignment_id, grades_data)
        else:
            log.warning("Grades JSON not found — skipping Firestore write and JSON upload.")

        # ── UPLOAD CSV ────────────────────────────────────────────────────────
        result_csv_url = ""
        if csv_file.exists():
            storage_csv_path = f"{result_base}/{assignment_id}_grades.csv"
            result_csv_url = upload_file(
                bucket, csv_file, storage_csv_path, content_type="text/csv"
            )
        else:
            candidates = list(local_output.rglob("*.csv"))
            if candidates:
                storage_csv_path = f"{result_base}/{assignment_id}_grades.csv"
                result_csv_url = upload_file(
                    bucket, candidates[0], storage_csv_path, content_type="text/csv"
                )

        # ── UPLOAD MULTI-PROBLEM EXTRAS ───────────────────────────────────────
        if assignment_type == "multi":
            for extra_pattern, ct in [
                (f"{assignment_id}_SUMMARY.json", "application/json"),
                (f"{assignment_id}_grades.xlsx",
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ]:
                extra_files = list(local_output.rglob(extra_pattern))
                if extra_files:
                    storage_path = f"{result_base}/{extra_files[0].name}"
                    upload_file(bucket, extra_files[0], storage_path, content_type=ct)

        # ── MARK COMPLETE ─────────────────────────────────────────────────────
        mark_complete(job_ref, result_json_url, result_csv_url, stl_folder_url)
        log.info(f"✓ Job {assignment_id} completed successfully.")

    finally:
        # Always clean up temp dir
        try:
            shutil.rmtree(tmp_root, ignore_errors=True)
            log.info(f"  Cleaned up temp dir: {tmp_root}")
        except Exception:
            pass

# ── MAIN POLLING LOOP ──────────────────────────────────────────────────────────

def main():
    setup_logging()
    log.info("=" * 60)
    log.info("SolidWorks Grading Agent starting up")
    log.info(f"Script dir : {SCRIPT_DIR}")
    log.info(f"Storage    : {STORAGE_BUCKET}")
    log.info(f"Log file   : {LOG_FILE}")
    log.info("=" * 60)

    backoff = POLL_INTERVAL_SECONDS

    while True:
        try:
            db, bucket = init_firebase()
            backoff = POLL_INTERVAL_SECONDS  # reset on successful connection

            pending = fetch_pending_jobs(db)

            if not pending:
                log.debug("No pending jobs. Sleeping...")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Process jobs one at a time
            for job_ref, job in pending:
                log.info(f"Found pending job: {job_ref.id} — {job.get('assignmentName', '?')}")
                mark_running(job_ref)
                try:
                    process_job(db, bucket, job_ref, job)
                except Exception as exc:
                    err_msg = str(exc)
                    log.error(f"Job {job_ref.id} failed: {err_msg}")
                    log.error(traceback.format_exc())
                    try:
                        mark_error(job_ref, err_msg)
                    except Exception:
                        log.error("Could not update job status to error in Firestore.")

            # Immediately check for more jobs before sleeping
            continue

        except KeyboardInterrupt:
            log.info("Grading agent stopped by user.")
            sys.exit(0)

        except Exception as exc:
            log.error(f"Unexpected agent error: {exc}")
            log.error(traceback.format_exc())
            log.info(f"Backing off for {backoff}s before retrying...")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)


if __name__ == "__main__":
    main()
