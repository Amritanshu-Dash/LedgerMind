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
    parser.add_argument("pdf_path", nargs="?", default=None, help="Path to the PDF file (for normal/smart mode)")
    parser.add_argument("--check", nargs="?", const=True, default=False, help="Check document health. Use --check for all documents or --check path/to/file.pdf")
    parser.add_argument("--reset", action="store_true", help="Reset the entire vector database and re-ingest")
    args = parser.parse_args()

    source_filename = Path(PDF_PATH).name    # " //////// ---------- removal may be needed "
    vector_store = VectorStore(persist_directory=PERSIST_DIRECTORY, collection_name=COLLECTION_NAME)

    # ====================== RESET MODE ======================
    if args.reset:
        print("⚠️ RESET MODE ACTIVATED")
        vector_store.reset_collection()
        if args.pdf_path:
            print(f"Re-ingesting: {args.pdf_path}")
            result = process_document(args.pdf_path)
            source = Path(args.pdf_path).name
            vector_store.add_chunks(chunks=result["chunks"], source_filename=source)
        else:
            print("No PDF provided. Collection has been reset but nothing was re-ingested.")
        
        return

    # ====================== CHECK MODE ======================
    if args.check is not False:
        print("🔍 CHECK MODE: Analyzing database health...\n")
        if args.check is True:
            #Global check - show all docs
            documents = vector_store.list_documents()
            if not documents:
                print("No documents found in the vector database.")
                return
            
            print(f"Found {len(documents)} document(s) in the database:\n")

            for idx, source in enumerate(documents, 1):
                info = vector_store.get_document_info(source)
                status = "✅ Healthy" if info.get("healthy") else "⚠️ Needs Re-ingestion"
                print(f"{idx}. {source}")
                print(f"   Chunks: {info.get('chunk_count', 0)} | Page Numbers: {info.get('has_page_number')} | Status: {status}\n")
        
        else:
            #Specific document check
            source = Path(args.check).name
            info = vector_store.get_document_info(source)

            print(f"Document: {source}")
            print(f"Exists in DB     : {info.get('exists')}")
            print(f"Chunk Count      : {info.get('chunk_count', 0)}")
            print(f"Has Page Numbers : {info.get('has_page_number')}")
            print(f"Healthy          : {info.get('healthy')}\n")

            if not info.get("healthy"):
                choice = input("Data looks incomplete. Do you want to re-ingest this document? (y/n): ").lower()
                if choice == "y":
                    vector_store.delete_document(source)
                    result = process_document(args.check)
                    vector_store.add_chunks(chunks=result["chunks"], source_filename=source)
                    print("✅ Re-ingestion completed.")

        return


    
    # ====================== DEFAULT SMART MODE ======================

    if not args.pdf_path:
        print("Error: Please provide a PDF path for normal mode.")
        print("Example: python run.py data/EX-21.1.pdf")
        return

    print("🚀 Starting LedgerMind Pipeline (Smart Mode)...\n")

    source_filename = Path(args.pdf_path).name
    info = vector_store.get_document_info(source_filename)

    if info.get("healthy"):
        print(f"✅ '{source_filename}' already exists and is healthy in the database.")
        print("Skipping ingestion. Proceeding to retrieval test...\n")
    else:
        print(f"⚠️ '{source_filename}' is missing or unhealthy in DB. Re-ingesting...\n")
        vector_store.delete_document(source_filename)
        result = process_document(args.pdf_path)
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
