"""
run.py
One-click runner for the full document ingestion pipeline.
It extracts, chunks, embeds, and stores documents in ChromaDB.
"""

import sys
from pathlib import Path

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from ingestion.document_pipeline import process_document
from ingestion.vector_store import VectorStore


if __name__ == "__main__":
    # ====================== CONFIGURATION ======================
    PDF_PATH = "/Users/amritanshudash/Desktop/LedgerMind/EX-21.1.pdf"
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200

    # Vector DB settings
    COLLECTION_NAME = "ledgermind_docs"
    PERSIST_DIRECTORY = "vector_db"
    # ===========================================================

    print("🚀 Starting full ingestion pipeline...\n")

    # Step 1: Process document (Extract + Clean + Chunk)
    result = process_document(
        pdf_path=PDF_PATH,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP
    )

    print("✅ Document processing complete!")
    print("=== Pipeline Stats ===")
    print(result["stats"])
    print(f"Total chunks created: {len(result['chunks'])}\n")

    # Step 2: Store chunks in Vector Database
    print("📦 Storing chunks in vector database...")

    vector_store = VectorStore(
        persist_directory=PERSIST_DIRECTORY,
        collection_name=COLLECTION_NAME
    )

    source_filename = Path(PDF_PATH).name

    vector_store.add_chunks(
        chunks=result["chunks"],
        source_filename=source_filename
    )

    # Final stats
    db_stats = vector_store.get_collection_stats()
    print("\n=== Vector Database Stats ===")
    print(db_stats)

    print("\n🎉 Ingestion pipeline completed successfully!")