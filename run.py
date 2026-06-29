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


def resolve_pdf_paths(input_paths):
    """Convert input (files or directory) into a clean list of PDF paths."""
    pdf_files = []
    for path_str in input_paths:
        path = Path(path_str)
        if path.is_dir():
            found = sorted(path.glob("*.pdf"))
            pdf_files.extend(found)
            print(f"📁 Found {len(found)} PDF(s) in folder: {path}")
        elif path.is_file() and path.suffix.lower() == ".pdf":
            pdf_files.append(path)
        else:
            print(f"⚠️ Skipping invalid path: {path}")
    return pdf_files



def main():

    parser = argparse.ArgumentParser(description="LedgerMind Ingestion Pipeline")
    parser.add_argument("paths", nargs = "*", help = "PDF file(s) or a folder containing PDFs")
    parser.add_argument("--check", nargs = "*", default = False, help = "Check health of documents. Can take files/folder or nothing for global check")
    parser.add_argument("--reset", nargs = "*", default = False, help="Reset and optionally re-ingest specific files/folder")
    args = parser.parse_args()

    vector_store = VectorStore(persist_directory=PERSIST_DIRECTORY, collection_name=COLLECTION_NAME)

    # ====================== RESET MODE ======================

    if args.reset is not False:

        print("⚠️ RESET MODE ACTIVATED")
        vector_store.reset_collection()

        if args.reset: # User provided path
            pdf_files = resolve_pdf_paths(args.reset)
            for pdf_path in pdf_files:
                print(f"Re-ingesting: {pdf_path.name}")
                result = process_document(str(pdf_path))
                vector_store.add_chunks(chunks=result["chunks"], source_filename=pdf_path.name)

        else:
            print("No PDF provided. Collection has been reset but nothing was re-ingested.")
        
        return

    # ====================== CHECK MODE ======================
    if args.check is not False:

        print("🔍 CHECK MODE: Analyzing database health...\n")

        if not args.check:
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
            pdf_files = resolve_pdf_paths(args.check)
            for pdf_path in pdf_files:
                source = pdf_path.name
                info = vector_store.get_document_info(source)
                status = "✅ Healthy" if info.get("healthy") else "⚠️ Needs Re-ingestion"
                print(f"📄 {source}")
                print(f"   Exists: {info.get('exists')} | Chunks: {info.get('chunk_count', 0)} | Healthy: {status}\n")
            
        return 


    
    # ====================== DEFAULT SMART MODE ======================

    if not args.paths:
        print("Error: Please provide a PDF file or a folder containing PDFs.")
        print("Examples:")
        print("  python run.py data/                    # Ingest all PDFs from data folder")
        print("  python run.py data/EX-21.1.pdf         # Ingest single PDF")
        print("  python run.py data/file1.pdf data/file2.pdf")
        return

    pdf_files = resolve_pdf_paths(args.paths)

    if not pdf_files:
        print("No valid PDF files found.")
        return
    
    print(f"\n🚀 Starting LedgerMind Pipeline for {len(pdf_files)} PDF(s)...\n")

    for pdf_path in pdf_files:
        source_filename = pdf_path.name
        print(f"--- Processing: {source_filename} ---")
        info = vector_store.get_document_info(source_filename)

        if info.get("healthy"):
            print(f"✅ Already healthy in DB. Skipping ingestion.\n")
        
        else:
            print(f"⚠️ Missing or unhealthy. Re-ingesting...\n")
            vector_store.delete_document(source_filename)
            result = process_document(str(pdf_path))
            vector_store.add_chunks(chunks=result["chunks"], source_filename=source_filename)
            print(f"✅ Ingestion completed for {source_filename}\n")

    print("🎉 All done!")


if __name__ == "__main__":
    main()


