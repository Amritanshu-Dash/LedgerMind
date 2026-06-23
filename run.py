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

    # ====================== DEBUG ======================
    print("\n=== DEBUG: Checking first 3 chunks ===")
    for i, chunk in enumerate(result["chunks"][:3]):
        print(f"Chunk {i+1}:")
        print(f"  page_number = {chunk.get('page_number')}")
        print(f"  text preview: {chunk['text'][:150]}...")
        print()
# =================================================

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

    # ====================== RETRIEVAL TEST ======================
    print("\n🔍 Testing Retrieval...\n")

    test_query = "What subsidiaries does Apple Hospitality REIT have?"

    print(f"Query: {test_query}")
    print("-" * 60)

    results = vector_store.query(query_text=test_query, n_results=3)

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]


    # ====================== RAW METADATA DEBUG ======================
    print("\n=== RAW METADATA FROM CHROMADB (first 2 results) ===")
    raw_metas = results.get("metadatas", [[]])[0][:2]
    for i, meta in enumerate(raw_metas):
        print(f"Result {i+1} metadata: {meta}")
    print("============================================================\n")
    # ================================================================


    #Display results
    for i, (doc, metadata, distance) in enumerate(zip(docs, metas, dists)):
        #safe distance formatting
        if isinstance(distance, (int, float)):
            dist_str = f"{distance:.4f}"
        else:
            dist_str = str(distance)

        page = metadata.get("page_number", "N/A")

        print(f"\nResult {i+1} (Distance: {dist_str}) | Page: {page}")
        print(f"Source: {metadata.get('source', 'N/A')}")
        print("-" * 40)
        print(doc[:700] + "..." if len(doc) > 700 else doc)
        print()