"""
Saves and reads rows in cache_queries.
This is only for questions.
File rows stay in the other repository.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ._00_connection import get_connection

logger = logging.getLogger(__name__)


class QueryCacheError(Exception):
    """Query row could not be saved or read."""

def insert_cache_query(
    original_query: str,
    system_converted_query: str,
    query_sense: str,
    attachment_count: int = 0,
    attachment_summary: str = "0 attachments",
) -> int:
    """
    Insert one question. Returns unique_query_id.
    Call this BEFORE saving any files for this question.
    """
    original_query = (original_query or "").strip()
    system_converted_query = (system_converted_query or "").strip()
    query_sense = (query_sense or "").strip()
    attachment_summary = (attachment_summary or "").strip() or "0 attachments"

    if not original_query:
        raise QueryCacheError("original_query is empty.")
    if not system_converted_query:
        raise QueryCacheError("system_converted_query is empty.")
    if not query_sense:
        raise QueryCacheError("query_sense is empty.")
    if not isinstance(attachment_count, int) or attachment_count < 0:
        raise QueryCacheError("attachment_count must be an integer >= 0.")

    sql = """
        INSERT INTO cache_queries (
            original_query,
            system_converted_query,
            query_sense,
            attachment_count,
            attachment_summary
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING unique_query_id;
    """

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        original_query,
                        system_converted_query,
                        query_sense,
                        attachment_count,
                        attachment_summary,
                    ),
                )
                row = cur.fetchone()
    except QueryCacheError:
        raise
    except Exception as e:
        raise QueryCacheError(f"Could not save query: {e}") from e

    if not row or row.get("unique_query_id") is None:
        raise QueryCacheError("Insert ran but no unique_query_id came back.")

    query_id = int(row["unique_query_id"])
    logger.info("Saved cache query %s (attachments=%s)", query_id, attachment_count)
    return query_id


def get_cache_query(unique_query_id: int) -> Optional[Dict[str, Any]]:
    """Return one query row, or None if it does not exist."""
    if not isinstance(unique_query_id, int) or unique_query_id < 1:
        raise QueryCacheError("unique_query_id must be a positive integer.")

    sql = """
        SELECT
            unique_query_id,
            original_query,
            system_converted_query,
            query_sense,
            attachment_count,
            attachment_summary,
            created_at
        FROM cache_queries
        WHERE unique_query_id = %s;
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (unique_query_id,))
                return cur.fetchone()
    except QueryCacheError:
        raise
    except Exception as e:
        raise QueryCacheError(f"Could not read query {unique_query_id}: {e}") from e