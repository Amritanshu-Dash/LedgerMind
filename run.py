"""
run.py
One-click runner for the full document ingestion pipeline.
Supports both PDF files and SEC EDGAR .txt filings.
Uses accession_number as unique ID for SEC filings.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict

# ====================== PATH FIX ======================
sys.path.append(str(Path(__file__).parent / "src"))
# ====================================================

from ingestion.pdf_file_ingestion import process_pdf
from ingestion.txt_file_ingestion import process_sec_filing
from ingestion.vector_store import VectorStore

# ====================== CONFIG ======================
PERSIST_DIRECTORY = "vector_db"
COLLECTION_NAME = "ledgermind_docs"
# ===================================================


def get_unique_source_id(file_path: Path, result: Dict[str, Any]) -> str:
    """
    Returns the best unique identifier for a document.
    - For SEC filings: uses accession_number
    - For PDFs: uses filename
    """
    if file_path.suffix.lower() == ".txt":
        # Try to get accession_number from first chunk's metadata
        if result.get("chunks"):
            first_chunk = result["chunks"][0]
            if isinstance(first_chunk, dict):
                acc_num = first_chunk.get("metadata", {}).get("accession_number")
                if acc_num:
                    return acc_num
            # If using LangChain Document style
            elif hasattr(first_chunk, "metadata"):
                acc_num = first_chunk.metadata.get("accession_number")
                if acc_num:
                    return acc_num
        # Fallback to filename if no accession number found
        return file_path.name

    # For PDF files, use filename
    return file_path.name


def resolve_file_paths(input_paths: List[str]) -> List[Path]:
    """Recursively find all supported files (.pdf and .txt)."""
    supported_files = []
    files_by_folder = defaultdict(list)

    for path_str in input_paths:
        path = Path(path_str)

        if path.is_dir():
            found = sorted(list(path.rglob("*.pdf")) + list(path.rglob("*.txt")))
            supported_files.extend(found)

            for f in found:
                folder_key = str(f.parent.relative_to(path) if f.parent != path else ".")
                files_by_folder[folder_key].append(f.name)

        elif path.is_file() and path.suffix.lower() in [".pdf", ".txt"]:
            supported_files.append(path)
            files_by_folder[str(path.parent)] = [path.name]
        else:
            print(f"⚠️ Skipping invalid path: {path}")

    if files_by_folder:
        print("\n📁 Found files:")
        for folder, files in files_by_folder.items():
            print(f"   📂 {folder}/")
            for fname in files:
                print(f"      └── {fname}")
        print(f"\nTotal: {len(supported_files)} file(s) found\n")

    return supported_files


def process_file(file_path: Path) -> Dict[str, Any]:
    """Unified processor that routes to correct handler based on file type."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        result = process_pdf(str(file_path))
        return result

    elif suffix == ".txt":
        documents = process_sec_filing(str(file_path))
        if not documents:
            return {"chunks": []}

        # Convert to simple chunk format for VectorStore compatibility
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
    parser = argparse.ArgumentParser(description="LedgerMind Ingestion Pipeline")
    parser.add_argument("paths", nargs="*", help="PDF or TXT file(s) or a folder")
    parser.add_argument("--check", nargs="*", default=False, help="Check health of documents")
    parser.add_argument("--reset", nargs="*", default=False, help="Reset and optionally re-ingest")

    args = parser.parse_args()
    vector_store = VectorStore(persist_directory=PERSIST_DIRECTORY, collection_name=COLLECTION_NAME)

    # ====================== RESET MODE ======================
    if args.reset is not False:
        print("⚠️ RESET MODE ACTIVATED")
        vector_store.reset_collection()

        # Collect paths from both args.paths and args.reset
        reset_paths = []
        if args.paths:
            reset_paths.extend(args.paths)
        if args.reset and isinstance(args.reset, list):
            reset_paths.extend(args.reset)

        if reset_paths:
            files = resolve_file_paths(reset_paths)
            if files:
                print(f"\n🔄 Re-ingesting {len(files)} file(s) after reset...\n")
                for file_path in files:
                    result = process_file(file_path)
                    if not result.get("chunks"):
                        print(f"⚠️ No chunks extracted from {file_path.name}. Skipping.\n")
                        continue

                    source_id = get_unique_source_id(file_path, result)
                    print(f"--- Re-ingesting: {source_id} ---")
                    vector_store.add_chunks(chunks=result["chunks"], source_filename=source_id)
                    print(f"✅ Done ({len(result['chunks'])} chunks)\n")
            else:
                print("No valid files found to re-ingest.")
        else:
            print("Collection has been reset but nothing was re-ingested.")
        return

    # ====================== CHECK MODE ======================
    if args.check is not False:
        print("🔍 CHECK MODE: Analyzing database health...\n")

        if not args.check:
            # Check all documents in DB
            documents = vector_store.list_documents()
            if not documents:
                print("No documents found in the vector database.")
                return

            for idx, source in enumerate(documents, 1):
                info = vector_store.get_document_info(source)
                meta = info.get("sample_metadata", {})

                status = "✅ Healthy" if info.get("healthy") else "⚠️ Needs Re-ingestion"

                ticker = meta.get("ticker") or ""
                company = meta.get("company_name") or ""
                filing_type = meta.get("filing_type") or ""
                period = meta.get("period_of_report") or ""

                header = f"{idx}. {source}"
                if ticker:
                    header = f"{idx}. {ticker} | {source}"

                print(header)
                if company or filing_type:
                    print(f"   Company: {company} | Type: {filing_type} | Period: {period}")
                print(f"   Chunks: {info.get('chunk_count', 0)} | Status: {status}\n")

        else:
            # Check specific paths provided by user
            files = resolve_file_paths(args.check)
            for file_path in files:
                result = process_file(file_path)
                source_id = get_unique_source_id(file_path, result) if result.get("chunks") else file_path.name
                info = vector_store.get_document_info(source_id)
                meta = info.get("sample_metadata", {})

                status = "✅ Healthy" if info.get("healthy") else "⚠️ Needs Re-ingestion"

                ticker = meta.get("ticker") or ""
                company = meta.get("company_name") or ""
                filing_type = meta.get("filing_type") or ""
                period = meta.get("period_of_report") or ""

                header = f"📄 {source_id}"
                if ticker:
                    header = f"📄 {ticker} | {source_id}"

                print(header)
                if company or filing_type:
                    print(f"   Company: {company} | Type: {filing_type} | Period: {period}")
                print(f"   Chunks: {info.get('chunk_count', 0)} | Status: {status}\n")

        return

    # ====================== DEFAULT SMART MODE ======================
    if not args.paths:
        print("Error: Please provide PDF or TXT file(s) or a folder containing them.")
        return

    files = resolve_file_paths(args.paths)
    if not files:
        print("No valid files found.")
        return

    print(f"\n🚀 Starting LedgerMind Pipeline for {len(files)} file(s)...\n")

    for file_path in files:
        result = process_file(file_path)
        if not result.get("chunks"):
            print(f"⚠️ No chunks extracted from {file_path.name}. Skipping.\n")
            continue

        source_id = get_unique_source_id(file_path, result)

        print(f"--- Processing: {source_id} ---")

        info = vector_store.get_document_info(source_id)
        if info.get("healthy"):
            print(f"✅ Already healthy in DB. Skipping ingestion.\n")
            continue

        print(f"⚠️ Missing or unhealthy. Re-ingesting...\n")
        vector_store.delete_document(source_id)
        vector_store.add_chunks(chunks=result["chunks"], source_filename=source_id)

        print(f"✅ Ingestion completed for {source_id} ({len(result['chunks'])} chunks)\n")

    print("🎉 All done!")


if __name__ == "__main__":
    main()