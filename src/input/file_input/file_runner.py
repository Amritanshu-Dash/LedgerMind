import logging
from pathlib import Path
from typing import Dict, Any

from .input import get_file
from .scanner import (
    scan_file,
    MalwareDetectedError,
    ScannerNotAvailableError
)

logger = logging.getLogger(__name__)


class FileProcessingError(Exception):
    """Raised when the overall file processing pipeline fails."""
    pass


def process_file(input_source: str, max_size_mb: float = 50.0) -> Dict[str, Any]:
    """
    Main orchestrator for file processing.

    Steps:
    1. Get / download the file (input_handler)
    2. Scan the file for malware (scanner)
    3. (Later) Extract content (extractor)

    Args:
        input_source: Local file path or public URL
        max_size_mb: Maximum allowed file size

    Returns:
        dict containing processing results

    Raises:
        FileProcessingError: On non-malware failures
        MalwareDetectedError: If the file is infected
    """
    logger.info(f"Starting file processing for: {input_source}")

    result = {
        "input_source": input_source,
        "local_path": None,
        "scan_status": None,
        "message": None,
        "success": False
    }

    try:
        # -------------------------
        # Step 1: Get the file
        # -------------------------
        local_path = get_file(input_source)
        result["local_path"] = local_path
        logger.info(f"File ready at: {local_path}")

        # Extra size check (optional but useful)
        actual_size_mb = Path(local_path).stat().st_size / (1024 * 1024)
        if actual_size_mb > max_size_mb:
            raise ValueError(
                f"File too large ({actual_size_mb:.2f} MB). Max allowed: {max_size_mb} MB"
            )

        # -------------------------
        # Step 2: Malware Scan
        # -------------------------
        scan_result = scan_file(
            file_path=local_path,
            max_size_mb=max_size_mb
        )

        result["scan_status"] = scan_result["status"]
        result["message"] = scan_result["message"]
        result["success"] = True

        logger.info(f"File processed successfully: {local_path}")
        return result

    except MalwareDetectedError as e:
        logger.warning(f"Malware detected: {e}")
        result["scan_status"] = "infected"
        result["message"] = str(e)
        e.result = result
        raise

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise FileProcessingError(str(e))

    except ScannerNotAvailableError as e:
        logger.error(f"Scanner not available: {e}")
        raise FileProcessingError(str(e))

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise FileProcessingError(str(e))

    except Exception as e:
        logger.error(f"Unexpected error during file processing: {e}")
        raise FileProcessingError(f"File processing failed: {str(e)}")


# ==============================
# Quick Test
# ==============================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    test_input = "/path/to/your/file.pdf"  # or a URL

    try:
        output = process_file(test_input)
        print("✅ Processing Result:")
        print(output)
    except MalwareDetectedError as e:
        print("❌ Infected file:", e)
        print("Partial result:", getattr(e, "result", None))
    except Exception as e:
        print("❌ Error:", str(e))