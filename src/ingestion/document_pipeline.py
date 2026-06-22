import sys
import time
from pathlib import Path
from typing import Dict, Any

# Add src folder to Python path so imports work
sys.path.append(str(Path(__file__).parent.parent))

from .document_reader import (
    extract_text_and_tables,
    clean_extracted_text,
    chunk_text
)

def process_document(pdf_path: str, chunk_size: int = 1000, chunk_overlap: int = 200, remove_page_markers: bool = False) -> Dict[str, Any]:

    """
    Main orchestrator function that runs the full document processing pipeline.

    Steps: Extract → Clean → Chunk → Return structured output with metadata and stats.
    """

    start_time = time.time()
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    # Step 1: Extract text and tables
    extraction_result = extract_text_and_tables(str(pdf_path))

    # Step 2: Clean the extracted text
    cleaned_text = clean_extracted_text (extraction_result["text"], remove_page_markers=remove_page_markers)

    # Step 3: Create chunks from cleaned text
    chunks = chunk_text(cleaned_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    processing_time = round(time.time() - start_time, 2)

    final_metadata = {**extraction_result["metadata"], "chunk_size": chunk_size, "chunk_overlap": chunk_overlap, "processing_time_seconds": processing_time}

    stats = {
        "total_pages": extraction_result["metadata"]["total_pages"],
        "total_tables": len(extraction_result["tables"]),
        "total_chunks": len(chunks),
        "total_characters_cleaned": len(cleaned_text),
        "processing_time_seconds": processing_time
    }

    return {
        "metadata": final_metadata,
        "chunks": chunks,
        "tables": extraction_result["tables"],
        "stats": stats
    }


# ====================== TEMPORARY TEST CODE ======================
# You can remove this section later when you start calling this from main.py

if __name__ == "__main__":
    pdf_path = "/Users/amritanshudash/Desktop/LedgerMind/EX-21.1.pdf"

    result = process_document(
        pdf_path=pdf_path,
        chunk_size=1000,
        chunk_overlap=200
    )

    print(result["stats"])
    print(f"\nTotal chunks created: {len(result['chunks'])}")

    if result["chunks"]:
        print("\n=== First Chunk Preview ===")
        print(result["chunks"][0]["text"][:300])
"""
#call 




result = extract_text_and_tables("/Users/amritanshudash/Desktop/LedgerMind/EX-21.1.pdf")

print(result["text"])           # Full extracted text
print(result["metadata"])       # PDF info
print(len(result["tables"]))    # Number of tables found

# Access first table
if result["tables"]:
    print(result["tables"])  


print("Clenaedddddddddddd")
# Basic usage (keeps page markers)
cleaned_text = clean_extracted_text(result["text"])

# If you want to remove page markers
cleaned_text = clean_extracted_text(result["text"], remove_page_markers=True)

print(cleaned_text)


print("\n\nchunkkkkkkkkkkkkkkkkkkkkkk\n\n")

chunks = chunk_text(cleaned_text, chunk_size=1000, chunk_overlap=200)

print(f"Total chunks created: {len(chunks)}")
print(chunks[0]["text"])        # First chunk
print(chunks[0]["char_count"])  # Size of first chunk

"""