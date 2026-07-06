"""
PDF Document Processor
Handles PDF files: extraction → cleaning → chunking
"""

import time
from pathlib import Path
from typing import Dict, Any, List

from .document_reader import (
    extract_text_and_tables,
    clean_extracted_text,
    chunk_text
)

def process_pdf( pdf_path: str, chunk_size: int = 1000, chunk_overlap: int = 200, remove_page_markers: bool = False) -> Dict[str, Any]:
    """
    Main function to process a PDF file.
    Extracts text + tables, cleans the content, and creates chunks.
    
    Returns a dictionary containing:
        - metadata
        - chunks (list of chunk dicts)
        - tables
        - stats
    """

    start_time = time.time()
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    print(f"Processing PDF: {pdf_path.name}")

    #Step 1: Extract text and tables from PDF
    extraction_result = extract_text_and_tables(str(pdf_path))

    #Step2: Clean the extacted text
    cleaned_text = clean_extracted_text(extraction_result["text"], remove_page_markers=remove_page_markers)

    #Step3: Create chunks
    chunks = chunk_text(cleaned_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    processing_time = round(time.time() - start_time, 2)

    #Final metadata
    final_metadata = {
        **extraction_result["metadata"],
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "processing_time_seconds": processing_time,
        "doc_type": "pdf"   
    }

    #Stats for logging
    stats = {
        "total_pages": extraction_result["metadata"].get("total_pages", 0),
        "total_tables": len(extraction_result.get("tables", [])),
        "total_chunks": len(chunks),
        "total_characters_cleaned": len(cleaned_text),
        "processing_time_seconds": processing_time  
    }

    print(f"Extracted {len(chunks)} chunks from {pdf_path.name} " f"({stats['total_pages']} pages, {stats['total_tables']} tables)")

    return {
        "metadata": final_metadata,
        "chunks": chunks,
        "tables": extraction_result.get("tables", []),
        "stats": stats
    }


if __name__ == "__main__":
    # Quick test
    test_pdf = "/Users/amritanshudash/Desktop/LedgerMind/EX-21.1.pdf"
    result = process_pdf(test_pdf, chunk_size=1000, chunk_overlap=200)
    print("\n=== Stats ===")
    print(result["stats"])
    if result["chunks"]:
        print("\n=== First Chunk Preview ===")
        print(result["chunks"][0]["text"][:400])