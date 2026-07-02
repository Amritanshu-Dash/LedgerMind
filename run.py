"""
run.py
One-click runner for the full document ingestion pipeline.
Supports both PDF files and SEC EDGAR .txt filings.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any

# ====================== PATH FIX ======================
sys.path.append(str(Path(__file__).parent / "src"))
# ====================================================

from ingestion.pdf_processor import process_pdf
from ingestion.sec_filing_processor import process_sec_filing
from ingestion.vector_store import VectorStore

# ====================== CONFIG ======================
PERSIST_DIRECTORY = "vector_db"
COLLECTION_NAME = "ledgermind_docs"
# ===================================================

def resolve_file_paths(input_paths: List[str]) -> List[Path]:
    """
    Recursively find all supported files (.pdf and .txt) from given paths.
    Shows organized output grouped by folder.
    """
    from collections import defaultdict

    supported_files = []
    files_by_folder = defaultdict(list)

    for path_str in input_paths:
        path = Path(path_str)

        if path.is_dir():
            # Recursive search for .pdf and .txt
            found = sorted(list(path.rglob("*.pdf")) + list(path.rglob("*.txt")))
            supported_files.extend(found)

            # Group files by their parent folder for nice logging
            for f in found:
                folder_key = str(f.parent.relative_to(path) if f.parent != path else ".")
                files_by_folder[folder_key].append(f.name)

        elif path.is_file() and path.suffix.lower() in [".pdf", ".txt"]:
            supported_files.append(path)
            files_by_folder[str(path.parent)] = [path.name]
        else:
            print(f"⚠️ Skipping invalid path: {path}")

    # Pretty print what was found
    if files_by_folder:
        print("\n📁 Found files:")
        for folder, files in files_by_folder.items():
            print(f"   📂 {folder}/")
            for fname in files:
                print(f"      └── {fname}")
        print(f"\nTotal: {len(supported_files)} file(s) found\n")

    return supported_files

def process_file(file_path: Path) -> Dict[str, Any]:
    """
    Unified processor that routes to correct handler based on file type.
    Returns a dict with 'chunks' key for compatibility with VectorStore.
    """

    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        result = process_pdf(str(file_path))
        return result #Already has 'chunks key
    
    elif suffix == ".txt":
        # process_sec_filing returns List[Document]
        documents = process_sec_filing(str(file_path))
        if not documents:
            return {"chunks": []}
        
        #Convert LangChain Documents to simple chunk format
        chunks = []
        for doc in documents:
            chunks.append({
                "text": doc.page_content,
                "metadata": doc.metadata
            })
        
        return {"chunks": chunks}
    
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
    
def main():
    parser = argparse.ArgumentParser(description="LedgerMind Ingestion Pipeline (PDF + SEC TXT)")
    parser.add_argument("paths", nargs="*", help="PDF or TXT file(s) or a folder containing them")
    parser.add_argument("--check", nargs="*", default=False, help="Check health of documents")
    parser.add_argument("--reset", nargs="*", default=False, help="Reset and optionally re-ingest")

    args = parser.parse_args()
    vector_store = VectorStore(persist_directory=PERSIST_DIRECTORY, collection_name=COLLECTION_NAME)

    # ====================== RESET MODE ======================
    if args.reset is not False:
        print("⚠️ RESET MODE ACTIVATED")
        vector_store.reset_collection()

        if args.reset:
            files = resolve_file_paths(args.reset)
            for file_path in files:
                print(f"Re-ingesting: {file_path.name}")
                result = process_file(file_path)
                vector_store.add_chunks(chunks=result["chunks"], source_filename=file_path.name)
        else:
            print("Collection has been reset but nothing was re-ingested.")
        return

    # ====================== CHECK MODE ======================
    if args.check is not False:
        print("🔍 CHECK MODE: Analyzing database health...\n")
        if not args.check:
            documents = vector_store.list_documents()
            if not documents:
                print("No documents found in the vector database.")
                return
            for idx, source in enumerate(documents, 1):
                info = vector_store.get_document_info(source)
                status = "✅ Healthy" if info.get("healthy") else "⚠️ Needs Re-ingestion"
                print(f"{idx}. {source}")
                print(f"   Chunks: {info.get('chunk_count', 0)} | Status: {status}\n")
        else:
            files = resolve_file_paths(args.check)
            for file_path in files:
                info = vector_store.get_document_info(file_path.name)
                status = "✅ Healthy" if info.get("healthy") else "⚠️ Needs Re-ingestion"
                print(f"📄 {file_path.name} | Chunks: {info.get('chunk_count', 0)} | Status: {status}")
        return

    # ====================== DEFAULT SMART MODE ======================
    if not args.paths:
        print("Error: Please provide PDF or TXT file(s) or a folder.")
        print("Examples:")
        print("  python run.py data/                    # All PDFs + TXTs from folder")
        print("  python run.py data/EX-21.1.pdf         # Single PDF")
        print("  python run.py data/AAPL_10K.txt        # Single SEC filing")
        return

    files = resolve_file_paths(args.paths)
    if not files:
        print("No valid .pdf or .txt files found.")
        return

    print(f"\n🚀 Starting LedgerMind Pipeline for {len(files)} file(s)...\n")

    for file_path in files:
        source_filename = file_path.name
        print(f"--- Processing: {source_filename} ---")

        info = vector_store.get_document_info(source_filename)
        if info.get("healthy"):
            print(f"✅ Already healthy in DB. Skipping ingestion.\n")
            continue

        print(f"⚠️ Missing or unhealthy. Re-ingesting...\n")
        vector_store.delete_document(source_filename)

        result = process_file(file_path)
        if result["chunks"]:
            vector_store.add_chunks(chunks=result["chunks"], source_filename=source_filename)
            print(f"✅ Ingestion completed for {source_filename} ({len(result['chunks'])} chunks)\n")
        else:
            print(f"⚠️ No chunks extracted from {source_filename}. Skipping.\n")

    print("🎉 All done!")


if __name__ == "__main__":
    main()   