"""
orchestrator.py (input section)
--------------------------------
Ties the input-section pipeline together: get the file, scan it, extract
its content. This file makes no decisions of its own about what's safe or
what's extractable — every real decision lives in input.py / scanner.py /
extractor.py. This file's only job is sequencing them and reporting a
single consistent result, whichever stage the pipeline stops at.

Design goals:
1. Never lose progress that already happened. If the file downloaded fine
   and passed the scan but extraction failed, the caller should still be
   able to see that — not just get a bare error string with everything
   before it thrown away.
2. Never leave a downloaded file sitting on disk longer than it needs to.
   Local files the user pointed to directly are never touched — only
   files THIS app downloaded into its own temp folder get cleaned up,
   and as soon as they've been processed (successfully or not), not on
   whatever schedule the lazy 24-hour reaper in input.py happens to run.
3. Shared limits come from scanner.py, same as input.py already does —
   no separate hardcoded copy of the size cap here to drift out of sync.
"""

import logging                            # structured logging instead of print()
from pathlib import Path                  # safe, OS-independent path handling
from typing import Any, Dict, Optional    # type hints so signatures are self-documenting

from .input import get_file, TEMP_DOWNLOAD_DIR
from .scanner import (
    scan_file,
    DEFAULT_MAX_SIZE_MB,                  # single source of truth, same constant input.py uses
    MalwareDetectedError,
    ScannerNotAvailableError,
    SuspiciousFileError,
)
from .extractor import extract_content, ExtractionError

logger = logging.getLogger(__name__)      # module-level logger tagged with this file's name


class FileProcessingError(Exception):
    """
    Raised when the overall file processing pipeline fails at any stage.

    Carries the partial `result` dict built up before the failure (e.g.
    local_path, scan_status if the scan already completed) so callers
    don't lose that context just because a later stage failed. This
    mirrors how MalwareDetectedError also gets a `.result` attached below
    — every failure path preserves whatever progress had already happened,
    not just the malware case.
    """
    def __init__(self, message: str, result: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.result = result


def _cleanup_downloaded_file(local_path: str) -> None:
    """
    Deletes a file ONLY if it lives inside input.py's own temp download
    directory — never touches a path the user supplied directly. Called
    after processing finishes, success or failure, so a downloaded file
    (especially one that turned out to be infected) doesn't linger on
    disk waiting for the next unrelated download to trigger cleanup.
    """
    try:
        resolved = Path(local_path).resolve()
        if resolved.parent == TEMP_DOWNLOAD_DIR.resolve():
            resolved.unlink(missing_ok=True)
            logger.debug(f"Cleaned up downloaded temp file: {resolved}")
    except Exception as e:
        # Cleanup failing is not itself a pipeline failure — log and move on.
        logger.warning(f"Could not clean up downloaded temp file {local_path}: {e}")


def process_file(input_source: str, max_size_mb: float = DEFAULT_MAX_SIZE_MB) -> Dict[str, Any]:
    """
    Full pipeline:
    1. Get / download the file
    2. Scan for malware (and structural issues — see scanner.py)
    3. Extract content (text + images via vision model)
    """
    logger.info(f"Starting file processing for: {input_source}")

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
        scan_result = scan_file(
            file_path=local_path,
            max_size_mb=max_size_mb,
            allowed_base_dir=str(TEMP_DOWNLOAD_DIR),  # only meaningful for downloaded files;
                                                        # see the note in scanner.py — a path
                                                        # outside this dir simply won't match,
                                                        # which is fine for user-supplied local files
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
        return result

    except MalwareDetectedError as e:
        logger.warning(f"Malware detected: {e}")
        result["scan_status"] = "infected"
        result["message"] = str(e)
        e.result = result  # attach partial progress for callers, same as FileProcessingError does
        raise

    except SuspiciousFileError as e:
        # Structural rejection (zip bomb, macro, PDF active content, magic
        # byte mismatch) — same fail-closed treatment as actual malware.
        logger.warning(f"File rejected on structural grounds: {e}")
        result["scan_status"] = "rejected"
        result["message"] = str(e)
        raise FileProcessingError(str(e), result=result)

    except ExtractionError as e:
        logger.error(f"Extraction failed: {e}")
        result["message"] = str(e)
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

    finally:
        # Whatever happened above — success, malware, or any other
        # failure — a file THIS app downloaded should not linger. User-
        # supplied local files are never touched (see _cleanup_downloaded_file).
        if local_path is not None:
            _cleanup_downloaded_file(local_path)


# ==============================
# Quick Test
# ==============================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Change this path to a real file on your system
    test_input = "/Users/amritanshudash/Downloads/sample.pdf"   # ← Change this

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