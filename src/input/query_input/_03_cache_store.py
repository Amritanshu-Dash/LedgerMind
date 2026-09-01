"""
_03_cache_store.py
------------------
Saves the query into cache DB.
Right now the query table is not built yet. So this file only prepares what we WOULD save, and returns a stub.
Later this file will call the query repository (new script in database_handlers). It should not open Postgres itself.
The shared connection file already does that.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _file_type(path: str) -> str:
    """
    pdf, xlsx, etc. from the file name. empty if we can't tell.
    """
    ext = Path(path).suffix.lower().lstrip(".")
    return ext or "unknown"


def _attachment_summary(attachments: List[str]) -> str:
    """
    Short line for the query row.
    Example: "1 pdf, 1 xlsx"
    """
    if not attachments:
        return "0 attachments"

    counts: Dict[str, int] = {}
    for path in attachments:
        kind = _file_type(path)
        counts[kind] = counts.get(kind, 0) + 1

    parts = [f"{n} {kind}" for kind, n in sorted(counts.items())]
    return ", ".join(parts)


def build_query_row(
    analysis: Dict[str, Any],
    attachments: List[str],
) -> Dict[str, Any]:
    """
    This is the data that will go into the QUERY table.
    Not the file table.
    File rows are separate and will use the query id later.
    """
    files = attachments or []
    return {
        "original_query": analysis.get("raw_query"),
        "system_converted_query": analysis.get("converted_query"),
        "query_sense": analysis.get("sense_for_model"),
        "intent": analysis.get("intent"),
        "in_scope": analysis.get("in_scope"),
        "ticker": analysis.get("ticker"),
        "attachment_count": len(files),
        "attachment_summary": _attachment_summary(files),
        "attachment_paths": files,
    }


def save_query_to_cache(
    analysis: Dict[str, Any],
    attachments: Optional[List[str]] = None,
    company_name: Optional[str] = None,
    company_stock_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Step we will do for real after the new table exists:
    1. Insert the query row.
    2. Get unique_query_id.
    3. For each file, save it in the file table with that same query id.
    Today: we do not touch the database. We only show the payload. If this function errors, orchestrator will skip prediction.
    """
    files = attachments or []
    row = build_query_row(analysis, files)

    logger.info(
        "Query save stub: intent=%s attachments=%s summary=%s",
        row["intent"],
        row["attachment_count"],
        row["attachment_summary"],
    )

    # When DB is ready, replace this return with a real insert
    # and put the new query id in unique_query_id.
    return {
        "status": "stub",
        "message": "Query table not wired yet. Nothing was saved.",
        "unique_query_id": None,
        "query_row": row,
        "company_name": company_name,
        "company_stock_name": company_stock_name,
        "files_to_save": files,
    }