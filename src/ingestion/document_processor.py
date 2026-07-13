"""
Document Processor (Unified Pipeline)
=====================================
Central module to process any supported document type (PDF, TXT, MD).
This acts as the main entry point for document ingestion in LedgerMind.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

#Import our existing ingestion modules
from .pdf_ingestion_module.pdf_ingestion import process_pdf
from .txt_md_ingestion_module.txt_md_ingestion import process_txt

def get_file_type(file_path : str) -> str:
    """Detect file type based on extension."""
    ext =   Path(file_path).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    elif ext in [".txt", ".md"]:
        return "text"
    else:
        return "unsupported"
    
def  process_document(file_path: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    remove_page_markers: bool = False
) -> Dict[str, Any]:
    """
    Unified function to process any supported document (PDF or TXT/MD).
    
    This is the main function you should use for document ingestion.
    """

    start_time = time.time()
    file_path_obj = Path(file_path)
    file_type = get_file_type(file_path)

    logger.info(f"Processing document: {file_path_obj.name} | Type: {file_type}")

    if file_type == "unsupported":
        raise ValueError(
            f"Unsupported file type: {file_path_obj.suffix}. "
            "Supported types: .pdf, .txt, .md"
        )

    try:
        if file_type == "pdf":
            result = process_pdf(
                pdf_path=file_path,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                remove_page_markers=remove_page_markers
            )
        else:  # text or markdown
            result = process_txt(
                file_path=file_path,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
        # Add common metadata
        total_time = round(time.time() - start_time, 2)
        result["pipeline_info"] = {
            "processed_by": "document_processor",
            "file_type_detected": file_type,
            "total_pipeline_time_seconds": total_time
        }

        logger.info(
            f"Successfully processed '{file_path_obj.name}' "
            f"({file_type}) in {total_time}s | Chunks: {result['stats']['total_chunks']}"
        )

        return result

    except Exception as e:
        logger.error(f"Failed to process document '{file_path_obj.name}': {str(e)}")
        raise


# ============================================================
#                      TESTING SECTION
# ============================================================
if __name__ == "__main__":
    # ============ UPDATE THESE PATHS ============
    test_pdf = "/Users/amritanshudash/Desktop/LedgerMind/data/EX-21.1.pdf"
    test_txt = "/Users/amritanshudash/Desktop/LedgerMind/data/raw/sec-edgar-filings/AAPL/10-K/0000320193-24-000123/full-submission.txt"   # ← Change this to a real .txt or .md file
    # ============================================

    print("\n" + "="*60)
    print("TESTING DOCUMENT PROCESSOR")
    print("="*60)

    # ---------- Test PDF ----------
    print("\n1. Testing PDF file...")
    try:
        result = process_document(test_pdf, chunk_size=1000, chunk_overlap=200)
        print(f"✅ PDF Success!")
        print(f"   File      : {result['file_info']['filename']}")
        print(f"   Chunks    : {result['stats']['total_chunks']}")
        print(f"   Time      : {result['pipeline_info']['total_pipeline_time_seconds']}s")
    except Exception as e:
        print(f"❌ PDF Failed: {e}")

    # ---------- Test TXT ----------
    print("\n2. Testing TXT/MD file...")
    try:
        result = process_document(test_txt, chunk_size=1000, chunk_overlap=200)
        print(f"✅ TXT Success!")
        print(f"   File      : {result['file_info']['filename']}")
        print(f"   Chunks    : {result['stats']['total_chunks']}")
        print(f"   Time      : {result['pipeline_info']['total_pipeline_time_seconds']}s")
    except Exception as e:
        print(f"❌ TXT Failed: {e}")

    print("\n" + "="*60)
    print("Testing completed.")
    print("="*60)
