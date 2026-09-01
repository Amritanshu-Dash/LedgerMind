"""
_01_orchestrator.py
-------------------
Runs the query pipeline in order.

This file owns:
- the user query string
- the attachment list (file paths)
- the sequence: analyze → (maybe) save → (maybe) predict

It does not clean the text itself and it does not talk to Postgres itself.
Those jobs live in _02_query_analysis and _03_cache_store.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._02_query_analysis import QueryAnalysisError, analyze_query
from ._03_cache_store import save_query_to_cache
from ._04_prediction import call_prediction_model

logger = logging.getLogger(__name__)


def _normalize_attachments(attachments: Optional[List[str]]) -> List[str]:
    """
    Turn the caller's attachment list into a clean list of path strings.
    - None → no files
    - drop empty entries
    - drop exact duplicates (same path twice should not count as two files)
    """
    if attachments is None:
        return []
    if not isinstance(attachments, list):
        raise QueryAnalysisError("attachments must be a list of file paths.")

    cleaned: List[str] = []
    seen = set()
    for item in attachments:
        if item is None:
            continue
        path = str(item).strip()
        if not path:
            continue
        # Resolve so ./a.pdf and a.pdf don't count as two files.
        try:
            key = str(Path(path).expanduser())
        except Exception:
            key = path
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(path)
    return cleaned


def process_query(
    query: str,
    attachments: Optional[List[str]] = None,
    company_name: Optional[str] = None,
    company_stock_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full query run.
    company_name / company_stock_name are only used later when a file is actually ingested. They are accepted here so the caller can pass them once when we wire process_file.
    """
    files = _normalize_attachments(attachments)

    # ----- 1. Analyze (must succeed or we stop) -----
    analysis = analyze_query(query, attachment_count=len(files))
    logger.info(
        "Query analyzed: intent=%s in_scope=%s needs_file=%s attachments=%s",
        analysis.get("intent"),
        analysis.get("in_scope"),
        analysis.get("needs_file"),
        len(files),
    )

    # ----- 2. Do not save or predict if the ask is unusable -----
    if not analysis.get("in_scope"):
        logger.info("Skipping save/predict: out of scope")
        return {
            "analysis": analysis,
            "saved": {"status": "skipped", "reason": "out_of_scope"},
            "prediction": {"status": "skipped", "reason": "out_of_scope"},
        }

    if analysis.get("needs_file") and not files:
        logger.info("Skipping save/predict: file required but none attached")
        return {
            "analysis": analysis,
            "saved": {"status": "skipped", "reason": "file_required"},
            "prediction": {"status": "skipped", "reason": "file_required"},
        }

    # ----- 3. Save (stub until the query table exists) -----
    try:
        saved = save_query_to_cache(
            analysis,
            files,
            company_name=company_name,
            company_stock_name=company_stock_name,
        )
    except Exception as e:
        logger.error("Cache save failed: %s", e)
        return {
            "analysis": analysis,
            "saved": {"status": "error", "error": str(e)},
            "prediction": {"status": "skipped", "reason": "save_failed"},
        }

    # ----- 4. Prediction stub (only after a successful save path) -----
    try:
        prediction = call_prediction_model(analysis, saved)
    except Exception as e:
        logger.error("Prediction stub failed: %s", e)
        return {
            "analysis": analysis,
            "saved": saved,
            "prediction": {"status": "error", "error": str(e)},
        }

    return {
        "analysis": analysis,
        "saved": saved,
        "prediction": prediction,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("Query pipeline (terminal)")
    print("File attachments: leave blank for query-only")
    print("=" * 60)

    text = input("Query: ")
    raw_files = input("Attachment paths (comma-separated, or empty): ").strip()
    paths = [p.strip() for p in raw_files.split(",")] if raw_files else []

    try:
        result = process_query(text, attachments=paths)
        print("\n----- ANALYSIS -----")
        for key, value in result["analysis"].items():
            print(f"{key}: {value}")
        print("\n----- SAVE -----")
        print(result["saved"])
        print("\n----- PREDICTION -----")
        print(result["prediction"])
    except QueryAnalysisError as e:
        print(f"\nQuery rejected: {e}")