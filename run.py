"""
run.py
One-click runner for the full document ingestion pipeline.
It extracts, chunks, embeds, and stores documents in ChromaDB.
"""

import argparse
import sys
from pathlib import Path

# ====================== PATH FIX ======================
# This allows us to import from src/ingestion/
sys.path.append(str(Path(__file__).parent / "src"))
# ====================================================

from ingestion.document_pipeline import process_document
from ingestion.vector_store import VectorStore


# ====================== CONFIG ======================
PDF_PATH = "/Users/amritanshudash/Desktop/LedgerMind/EX-21.1.pdf"
PERSIST_DIRECTORY = "vector_db"
COLLECTION_NAME = "ledgermind_docs"
# ===================================================


def main():
    parser = argparse.ArgumentParser(description="LedgerMind Ingestion Pipeline")
    parser.add_argument("--reset", action="store_true", help="Reset the entire vector database and re-ingest")
    parser.add_argument("--check", action="store_true", help="Only check the health of current document in DB")
    args = parser.parse_args()

    source_filename = Path(PDF_PATH).name
    vector_store = VectorStore(persist_directory=PERSIST_DIRECTORY, collection_name=COLLECTION_NAME)

    # ====================== RESET MODE ======================
    if args.reset:
        print("⚠️ RESET MODE ACTIVATED")
        vector_store.reset_collection()
        print("Re-ingesting document from scratch...\n")
        result = process_document(PDF_PATH)
        vector_store.add_chunks(chunks=result["chunks"], source_filename=source_filename)
        print("\n✅ Reset + Re-ingestion completed.")
        return

    # ====================== CHECK MODE ======================
    if args.check:
        print("🔍 CHECK MODE: Analyzing database health...\n")
        info = vector_store.get_document_info(source_filename)
        print(f"Document: {source_filename}")
        print(f"Exists in DB     : {info.get('exists')}")
        print(f"Chunk Count      : {info.get('chunk_count', 0)}")
        print(f"Has Page Numbers : {info.get('has_page_number')}")
        print(f"Healthy          : {info.get('healthy')}\n")

        if not info.get("healthy"):
            choice = input("Data looks incomplete. Do you want to re-ingest? (y/n): ").lower()
            if choice == "y":
                vector_store.delete_document(source_filename)
                result = process_document(PDF_PATH)
                vector_store.add_chunks(chunks=result["chunks"], source_filename=source_filename)
                print("✅ Re-ingestion completed.")
    
        return
    
    # ====================== DEFAULT SMART MODE ======================
    print("🚀 Starting LedgerMind Pipeline (Smart Mode)...\n")

    info = vector_store.get_document_info(source_filename)

    if info.get("healthy"):
        print(f"✅ '{source_filename}' already exists and is healthy in the database.")
        print("Skipping ingestion. Proceeding to retrieval test...\n")
    else:
        print(f"⚠️ '{source_filename}' is missing or unhealthy in DB. Re-ingesting...\n")
        vector_store.delete_document(source_filename)
        result = process_document(PDF_PATH)
        vector_store.add_chunks(chunks=result["chunks"], source_filename=source_filename)
        print("✅ Ingestion completed.\n")

    # ====================== RETRIEVAL TEST ======================
    print("🔍 Running Retrieval Test...\n")
    test_query = "What subsidiaries does Apple Hospitality REIT have?"
    results = vector_store.query(query_text=test_query, n_results=3)

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    for i, (doc, metadata, distance) in enumerate(zip(docs, metas, dists)):
        dist_str = f"{distance:.4f}" if isinstance(distance, (int, float)) else str(distance)
        page = metadata.get("page_number", "N/A")

        print(f"Result {i+1} (Distance: {dist_str}) | Page: {page}")
        print(f"Source: {metadata.get('source', 'N/A')}")
        print("-" * 50)
        print(doc[:600] + "..." if len(doc) > 600 else doc)
        print()

    print("\n🎉 Pipeline finished successfully!")


if __name__ == "__main__":
    main()
