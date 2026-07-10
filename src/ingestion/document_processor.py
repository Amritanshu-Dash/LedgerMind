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

from chromadb import logger

#Import our existing ingestion modules
from .pdf_ingestion_module.pdf_ingestion import process_pdf
from .txt_md_ingestion_module.txt_md_ingestion import process_txt

logger - logging.getLogger(__name__)

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
            f"({file_type}) in {total_time}s"
        )

        return result

    except Exception as e:
        logger.error(f"Failed to process document '{file_path_obj.name}': {str(e)}")
        raise


# Optional: Quick test function
if __name__ == "__main__":
    # Example usage
    test_pdf = "/Users/amritanshudash/Desktop/LedgerMind/data/EX-21.1.pdf"
    test_txt = "/path/to/your/test.txt"

    try:
        result = process_document(test_pdf)
        print(f"PDF processed successfully. Chunks: {result['stats']['total_chunks']}")
    except Exception as e:
        print(f"Error: {e}")
