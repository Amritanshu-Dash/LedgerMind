"""
Document Processor (Unified Pipeline)
=====================================
Central module to process any supported document type (PDF, TXT, MD).
This acts as the main entry point for document ingestion in LedgerMind.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

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

# Import ChromaDB store
from database.chroma_store import ChromaStore

def get_file_type(file_path : str) -> str:
    """Detect file type based on extension."""
    ext =   Path(file_path).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    elif ext in [".txt", ".md"]:
        return "text"
    else:
        return "unsupported"
    
def process_document(
    file_path: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    remove_page_markers: bool = False,
    store_in_db: bool = True,
) -> Dict[str, Any]:
    """
    Unified function to process any supported document and optionally store in ChromaDB.
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


        # Store in ChromaDB
        if store_in_db and result.get("chunks"):

            store = ChromaStore()
            chunks = result["chunks"]
            texts = [chunk["text"] for chunk in chunks]
            metadatas = []

            for chunk in chunks:
                meta = {
                    "filename": result["file_info"]["filename"],
                    "file_type": file_type,
                    "page_number": chunk.get("page_number", 1),
                    "chunk_id": chunk.get("chunk_id"),
                    "char_count": chunk.get("char_count"),
                }
                metadatas.append(meta)
            
            store.add_chunks(chunks=texts, metadatas=metadatas)
            logger.info(f"Stored {len(result['chunks'])} chunks in ChromaDB.")    

        # Add common metadata
        total_time = round(time.time() - start_time, 2)
        result["pipeline_info"] = {
            "processed_by": "document_processor",
            "file_type_detected": file_type,
            "total_pipeline_time_seconds": total_time,
            "stored_in_db": store_in_db
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
# TESTING SECTION
# ============================================================
if __name__ == "__main__":
    test_pdf = "/Users/amritanshudash/Desktop/LedgerMind/data/EX-21.1.pdf"

    print("\n" + "="*60)
    print("TESTING DOCUMENT PROCESSOR + CHROMADB")
    print("="*60)

    try:
        result = process_document(
            test_pdf,
            chunk_size=1000,
            chunk_overlap=200,
            store_in_db=True
        )
        print(f"\n✅ Success!")
        print(f"File     : {result['file_info']['filename']}")
        print(f"Chunks   : {result['stats']['total_chunks']}")
        print(f"Time     : {result['pipeline_info']['total_pipeline_time_seconds']}s")
        print(f"Stored in DB: {result['pipeline_info']['stored_in_db']}")
    except Exception as e:
        print(f"\n❌ Failed: {e}")

    print("\n" + "="*60)
