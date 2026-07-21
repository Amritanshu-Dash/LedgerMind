import logging
from pathlib import Path
from typing import Dict, Any

from .input import get_file
from .scanner import (
    scan_file,
    MalwareDetectedError,
    ScannerNotAvailableError
)
from .extractor import extract_content, ExtractionError

logger = logging.getLogger(__name__)


class FileProcessingError(Exception):
    """Raised when the overall file processing pipeline fails."""
    pass


def process_file(input_source: str, max_size_mb: float = 50.0) -> Dict[str, Any]:
    """
    Full pipeline:
    1. Get / download the file
    2. Scan for malware
    3. Extract content (text + images via vision model)
    """
    logger.info(f"Starting file processing for: {input_source}")

    result = {
        "input_source": input_source,
        "local_path": None,
        "scan_status": None,
        "message": None,
        "success": False,
        "extraction": None
    }

    try:
        # -------------------------
        # Step 1: Get the file
        # -------------------------
        local_path = get_file(input_source)
        result["local_path"] = local_path
        logger.info(f"File ready at: {local_path}")

        # Size check
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
        e.result = result
        raise

    except ExtractionError as e:
        logger.error(f"Extraction failed: {e}")
        raise FileProcessingError(str(e))

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
    except Exception as e:
        print("❌ Error:", str(e))