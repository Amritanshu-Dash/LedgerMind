"""
_01_intake.py
-------------
Front door: query + optional local file paths.

Ask for both first, then save the query (so analysis knows if files exist),
then process each file with that unique_query_id.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.input.file_input._01_orchestrator import process_file
from src.input.query_input._01_orchestrator import process_query
from src.input.query_input._02_query_analysis import QueryAnalysisError

logger = logging.getLogger(__name__)


def _paths_from_input(raw: str) -> list[str]:
    if not raw.strip():
        return []
    parts = [p.strip().strip("'\"") for p in raw.split(",")]
    return [p for p in parts if p]


def run_intake() -> None:
    query = input("Query: ").strip()
    raw_files = input("File paths (comma-separated, or empty for none): ")
    paths = _paths_from_input(raw_files)

    try:
        result = process_query(query, attachments=paths)
    except QueryAnalysisError as e:
        print(f"Query rejected: {e}")
        return

    analysis = result.get("analysis") or {}
    saved = result.get("saved") or {}

    print("\n----- ANALYSIS -----")
    print("intent:", analysis.get("intent"))
    print("in_scope:", analysis.get("in_scope"))
    print("user_message:", analysis.get("user_message"))

    query_id = saved.get("unique_query_id")
    print("\n----- SAVE -----")
    print("status:", saved.get("status"))
    print("unique_query_id:", query_id)

    if not query_id:
        print("\nNo query id. Stopping.")
        return

    print(f"\nOK. Query saved as {query_id}.")

    if not paths:
        print("No files. Done.")
        return

    company_name = input("Company name (for file rows): ").strip() or "UNKNOWN"
    company_stock = input("Ticker (for file rows): ").strip() or (
        analysis.get("ticker") or "UNKNOWN"
    )

    saved_files = []
    failed_files = []

    for index, path in enumerate(paths, start=1):
        print("\n" + "=" * 60)
        print(f"FILE {index}/{len(paths)}: {path}")
        print("=" * 60)

        if not Path(path).is_file():
            print(f"Cannot process. Not a file: {path}")
            failed_files.append({"path": path, "error": "not a file"})
            continue

        try:
            file_result = process_file(
                path,
                company_name=company_name,
                company_stock_name=company_stock,
                unique_query_id=query_id,
            )
            file_id = file_result.get("cache_document_id")
            print(f"FILE {index} saved. file_id={file_id} query_id={query_id}")
            saved_files.append({"path": path, "file_id": file_id})
        except TypeError as e:
            print(
                f"FILE {index} failed. process_file may still be missing "
                f"unique_query_id: {e}"
            )
            failed_files.append({"path": path, "error": str(e)})
        except Exception as e:
            print(f"FILE {index} failed: {e}")
            failed_files.append({"path": path, "error": str(e)})

    print("\n----- FILE SUMMARY -----")
    print("saved:", saved_files)
    print("failed:", failed_files)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print("=" * 60)
    print("LedgerMind intake (query + optional files)")
    print("=" * 60)
    run_intake()