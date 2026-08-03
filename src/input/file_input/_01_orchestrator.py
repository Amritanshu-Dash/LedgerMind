"""
orchestrator.py (input section)
--------------------------------
Ties the input-section pipeline together: 
-> get the file, scan it, extract its content. This file makes no decisions of its own about what's safe or what's extractable — every real decision lives in input.py / scanner.py / extractor.py. This file's only job is sequencing them and reporting a
single consistent result, whichever stage the pipeline stops at.

Design goals:
1. Never lose progress that already happened. If the file downloaded fine and passed the scan but extraction failed, the caller should still be able to see that — not just get a bare error string with everything before it thrown away.
2. Only delete a downloaded file immediately when it's been CONFIRMED dangerous (malware or a structural rejection). A downloaded file that passed the scan but then failed at extraction is OUR bug, not the file's fault — it gets archived (not deleted) into failed_extraction/,
   alongside the error that explains what went wrong, so it can be inspected later. A successfully processed file gets archived the same way into extracted_files/, alongside its extraction result. Local files the user pointed to directly are COPIED into these archive
   folders, never moved or deleted — only files this app downloaded are ever candidates for deletion or being moved out of their original location.
3. Shared limits come from constants.py, same as input.py already does — no separate hardcoded copy of the size cap here to drift out of sync.
"""

import json                               # writes the extraction result / error as a sidecar file
import logging                            # structured logging instead of print()
import shutil                             # moves (owned files) or copies (user files) into archive folders
from pathlib import Path                  # safe, OS-independent path handling
from typing import Any, Dict, Optional    # type hints so signatures are self-documenting
from uuid import uuid4                    # ties an archived original and its result file together by name

from ._00_constants import DEFAULT_MAX_UPLOAD_FILE_SIZE_MB, TEMP_DOWNLOAD_DIRECTORY_PATH
from ._02_input import get_file, cleanup_old_temp_files
from ._03_scanner import (
    scan_file,
    MalwareDetectedError,
    ScannerNotAvailableError,
    SuspiciousFileError,
)
from ._04_extractor import extract_content, ExtractionError

logger = logging.getLogger(__name__)      # module-level logger tagged with this file's name


# ==============================
# Configuration
# ==============================
# Archive folders — local to this file only (nothing else needs to know about them), so they stay defined here rather than in constants.py.
EXTRACTED_FILES_DIRECTORY = Path(__file__).resolve().parent / "extracted_files"
FAILED_EXTRACTION_DIRECTORY = Path(__file__).resolve().parent / "failed_extraction"


class FileProcessingError(Exception):
    """
    Raised when the overall file processing pipeline fails at any stage.

    Carries the partial `result` dict built up before the failure (e.g. local_path, scan_status if the scan already completed) so callers don't lose that context just because a later stage failed. This mirrors how MalwareDetectedError also gets a `.result` attached below
    — every failure path preserves whatever progress had already happened, not just the malware case.
    """
    def __init__(self, message: str, result: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.result = result


def _is_downloaded_temp_file(local_path: str) -> bool:
    """
    True only if this path lives inside input.py's own temp download directory — i.e. this app downloaded it itself, as opposed to the user pointing directly at a file somewhere else on their own disk.
    """
    try:
        return Path(local_path).resolve().parent == TEMP_DOWNLOAD_DIRECTORY_PATH.resolve()
    except Exception:
        return False


def _cleanup_downloaded_file(local_path: str) -> None:
    """
    Deletes a file ONLY if it lives inside input.py's own temp download directory — never touches a path the user supplied directly. Meant to be called specifically when a downloaded file has been confirmed dangerous (malware / structural rejection) — NOT on every outcome, see
    process_file()'s finally block for why.
    """
    if not _is_downloaded_temp_file(local_path):
        return  # never delete a file the user pointed to directly
    try:
        Path(local_path).unlink(missing_ok=True)
        logger.debug(f"Cleaned up downloaded temp file: {local_path}")
    except Exception as e:
        logger.warning(f"Could not clean up downloaded temp file {local_path}: {e}")


def _archive_processed_file(
    local_path: str,
    extraction_result: Optional[Dict[str, Any]],
    error_message: Optional[str],
) -> Optional[str]:
    """
    Files a processed document away for review, together with what came out of it — both the original file AND its extraction result (or error) land in the same folder, named with a shared id so the pair is
    easy to find together later:
      extracted_files/<id>_<original filename>
      extracted_files/<id>_result.json
    or, on an extraction failure, the same pair under failed_extraction/.

    A downloaded file is MOVED (this app owns it, safe to relocate) — a local file the user pointed to directly is only ever COPIED, never moved or deleted, regardless of outcome.

    Returns the archived original's new path if a downloaded file was moved (so the caller can keep result["local_path"] pointing at a file that actually still exists), or None if nothing moved (a copy of a local file leaves the original — and therefore local_path — right
    where it was) or if archiving failed outright.

    Archiving failures are logged, never raised — losing the audit copy is not worth turning a successful (or already-explained) pipeline run into a hard failure.
    """
    is_success = extraction_result is not None
    target_dir = EXTRACTED_FILES_DIRECTORY if is_success else FAILED_EXTRACTION_DIRECTORY
    was_downloaded = _is_downloaded_temp_file(local_path)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)

        original = Path(local_path)
        archive_id = uuid4().hex
        archived_original_path = target_dir / f"{archive_id}_{original.name}"

        if was_downloaded:
            shutil.move(str(original), str(archived_original_path))
        else:
            shutil.copy2(str(original), str(archived_original_path))

        sidecar_path = target_dir / f"{archive_id}_result.json"
        payload = extraction_result if is_success else {"error": error_message}
        sidecar_path.write_text(json.dumps(payload, indent=2, default=str))

        logger.info(f"Archived {'successful' if is_success else 'failed'} result to: {target_dir}")
        return str(archived_original_path) if was_downloaded else None
    except Exception as e:
        logger.warning(f"Could not archive processed file {local_path}: {e}")
        return None


def process_file(input_source: str, max_size_mb: float = DEFAULT_MAX_UPLOAD_FILE_SIZE_MB) -> Dict[str, Any]:
    """
    Full pipeline:
    1. Get / download the file
    2. Scan for malware (and structural issues — see scanner.py)
    3. Extract content (text + images via vision model)
    """
    logger.info(f"Starting file processing for: {input_source}")

    # Sweep old downloaded temp files on every pipeline run, not just when
    # a new download happens — otherwise a stretch of days with no
    # downloads means nothing ever triggers the cleanup at all. For a
    # guarantee that holds even when the app isn't running (e.g. a whole
    # week goes by with no one opening it), this needs to be paired with
    # an OS-level scheduled job (cron / launchd) — this call alone only
    # helps while the app is actually being used.
    cleanup_old_temp_files()

    result: Dict[str, Any] = {
        "input_source": input_source,
        "local_path": None,
        "scan_status": None,
        "message": None,
        "success": False,
        "extraction": None,
    }

    local_path: Optional[str] = None

    try:
        # -------------------------
        # Step 1: Get the file
        # -------------------------
        local_path = get_file(input_source)
        result["local_path"] = local_path
        logger.info(f"File ready at: {local_path}")

        # -------------------------
        # Step 2: Malware / structural scan
        # -------------------------
        # The directory containment check only makes sense for files THIS
        # app downloaded — a local file the user pointed to directly can
        # legitimately live anywhere they have read access to, so it gets
        # no containment restriction (None disables that check entirely,
        # see scanner.py).
        base_dir = str(TEMP_DOWNLOAD_DIRECTORY_PATH) if _is_downloaded_temp_file(local_path) else None
        scan_result = scan_file(
            file_path=local_path,
            max_size_mb=max_size_mb,
            allowed_base_dir=base_dir,
        )

        result["scan_status"] = scan_result.status
        result["message"] = f"Passed all safety checks: {', '.join(scan_result.checks_passed)}"

        # -------------------------
        # Step 3: Content Extraction
        # -------------------------
        logger.info("Starting content extraction...")
        extraction_result = extract_content(local_path)
        result["extraction"] = extraction_result

        result["success"] = True
        logger.info(f"File processed successfully: {local_path}")
        archived_path = _archive_processed_file(local_path, extraction_result=extraction_result, error_message=None)
        if archived_path is not None:
            result["local_path"] = archived_path  # file was moved — keep this pointing at where it actually is
        return result

    except MalwareDetectedError as e:
        logger.warning(f"Malware detected: {e}")
        result["scan_status"] = "infected"
        result["message"] = str(e)
        e.result = result  # attach partial progress for callers, same as FileProcessingError does
        if local_path is not None:
            _cleanup_downloaded_file(local_path)  # confirmed dangerous — delete immediately, don't wait
        raise

    except SuspiciousFileError as e:
        # Structural rejection (zip bomb, macro, PDF active content, magic
        # byte mismatch) — same fail-closed, delete-immediately treatment
        # as actual malware. Not inherently malicious, but not something
        # worth keeping around either.
        logger.warning(f"File rejected on structural grounds: {e}")
        result["scan_status"] = "rejected"
        result["message"] = str(e)
        if local_path is not None:
            _cleanup_downloaded_file(local_path)
        raise FileProcessingError(str(e), result=result)

    except ExtractionError as e:
        # The file itself passed the scan clean — this failure is ours
        # (extraction logic, an unusual document, a genuine bug), not the
        # file's fault. Archived into failed_extraction/ (original +
        # error message side by side) so it's easy to find and debug,
        # rather than deleted or left sitting in the temp download folder.
        logger.error(f"Extraction failed: {e}")
        result["message"] = str(e)
        if local_path is not None:
            archived_path = _archive_processed_file(local_path, extraction_result=None, error_message=str(e))
            if archived_path is not None:
                result["local_path"] = archived_path
        raise FileProcessingError(str(e), result=result)

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        result["message"] = str(e)
        raise FileProcessingError(str(e), result=result)

    except ScannerNotAvailableError as e:
        logger.error(f"Scanner not available: {e}")
        result["message"] = str(e)
        raise FileProcessingError(str(e), result=result)

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        result["message"] = str(e)
        raise FileProcessingError(str(e), result=result)

    except Exception as e:
        logger.error(f"Unexpected error during file processing: {e}")
        result["message"] = str(e)
        raise FileProcessingError(f"File processing failed: {str(e)}", result=result)

    # No finally-block cleanup here on purpose. A downloaded file only gets
    # deleted immediately when it's been CONFIRMED dangerous (the two
    # except branches above do that explicitly). On success or an
    # extraction failure, the file gets archived instead (see
    # _archive_processed_file) — moved (if downloaded) or copied (if
    # local) into extracted_files/ or failed_extraction/, alongside its
    # result or error. Any OTHER failure (scanner unavailable, file not
    # found, etc) leaves the file untouched at its original location —
    # there's no extraction outcome to file away yet. The 24-hour sweep
    # (cleanup_old_temp_files, run at the top of this function and inside
    # input.py's download path) clears out anything left over in the temp
    # download folder itself.


# ==============================
# Quick Test
# ==============================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Change this path to a real file on your system
    test_input = "/Users/amritanshudash/Desktop/LedgerMind/data/EX-21.1.pdf"   # ← Change this

    try:
        output = process_file(test_input)
        print("\n" + "="*60)
        print("✅ PROCESSING SUCCESSFUL")
        print("="*60)
        print(f"Local Path     : {output['local_path']}")
        print(f"Scan Status    : {output['scan_status']}")
        print(f"File Type      : {output['extraction']['file_type']}")
        print(f"Images Found   : {output['extraction']['images_found']}")
        print("\n----- Extracted Text (first 1000 chars) -----")
        print(output['extraction']['text'][:1000])
        print("...")
    except MalwareDetectedError as e:
        print("❌ Infected file:", e)
    except FileProcessingError as e:
        print("❌ Processing failed:", str(e))
        if e.result:
            print("   Partial progress:", {k: v for k, v in e.result.items() if k != "extraction"})
    except Exception as e:
        print("❌ Unexpected error:", str(e))
