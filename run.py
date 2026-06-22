"""
run.py
Simple runner script for the document processing pipeline.
Just run: python run.py
"""

import sys
from pathlib import Path

# Add src folder to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from ingestion.document_pipeline import process_document


if __name__ == "__main__":
    # ====================== CONFIGURATION ======================
    PDF_PATH = "/Users/amritanshudash/Desktop/LedgerMind/EX-21.1.pdf"

    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200
    # ===========================================================

    print("🚀 Starting document processing pipeline...\n")

    result = process_document(
        pdf_path=PDF_PATH,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP
    )

    print("✅ Processing complete!\n")
    print("=== STATS ===")
    print(result["stats"])

    print(f"\nTotal chunks created: {len(result['chunks'])}")

    if result["chunks"]:
        print("\n=== First Chunk Preview ===")
        print(result["chunks"][0]["text"][:400])
        print("...")