"""
_02_query_analysis.py
---------------------
Takes the raw user query and turns it into a structured result.

Two jobs in this one file (they belong together):
1. Clean the text so we are not matching on messy spaces / junk characters.
2. Guess what the user is asking (intent) with simple rules.

This is NOT the prediction model.
This is NOT the database.
If this step fails, the orchestrator must not save and must not predict.

v1 uses keyword rules. A grammar tool or a small text model can be
plugged into the functions below later without changing the dict shape.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from ._00_constants import (
    DOCUMENT_KEYWORDS,
    FINANCE_KEYWORDS,
    INSIGHT_KEYWORDS,
    INTENT_COMPANY_INSIGHT,
    INTENT_INSIGHTS_ON_DOCUMENT,
    INTENT_OTHER_FINANCE,
    INTENT_OUT_OF_SCOPE,
    INTENT_SUMMARIZE_DOCUMENT,
    INTENT_UNCLEAR,
    MAX_ATTACHMENTS,
    MAX_QUERY_CHARS,
    MIN_QUERY_CHARS,
    SUMMARIZE_KEYWORDS,
)

logger = logging.getLogger(__name__)


class QueryAnalysisError(Exception):
    """
    Raised when the query cannot be used at all.
    Examples: missing text, not a string, empty after cleaning, too long. The orchestrator catches this and stops the pipeline.
    """


# One-or-more whitespace (spaces, tabs, newlines) → we collapse to a single space.
_WHITESPACE_RE = re.compile(r"\s+")

# Invisible control characters that can break logs or the database.
# We delete these; we do not delete normal letters or punctuation.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Crude ticker guess: 1–5 capital letters standing alone, e.g. APLE, AAPL.
_TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")

# Capital words that look like tickers but usually are not.
_COMMON_CAPS = {"I", "A", "PDF", "SEC", "ETF", "USD", "CEO", "AI", "ML", "OK"}


def _require_text(query: Any) -> str:
    """
    Make sure we actually got a string.
    People (and tests) might pass None or a number. Fail early with a clear message instead of crashing inside .strip().
    """
    if query is None:
        raise QueryAnalysisError("Query is missing.")
    if not isinstance(query, str):
        raise QueryAnalysisError(f"Query must be text, got {type(query).__name__}.")
    return query


def _clean(raw: str) -> str:
    """
    Build the working copy of the query.

    - trim the ends
    - normalize Windows/Mac newlines
    - drop control characters
    - squeeze repeated spaces into one space

    The original string is still stored separately as raw_query.
    """
    try:
        text = raw.strip()
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _CONTROL_RE.sub("", text)
        text = _WHITESPACE_RE.sub(" ", text).strip()
        return text
    except Exception as e:
        # Cleaning should never crash the app with a raw unexpected error.
        raise QueryAnalysisError(f"Could not clean the query: {e}") from e


def _apply_grammar(cleaned: str) -> str:
    """
    Optional grammar rewrite.
    v1: do nothing. Return the cleaned text as the 'converted' query. Later you can call a grammar tool here.
    If that tool fails, we keep the cleaned text and log a warning. We do not fail the whole analysis just because grammar failed.
    """
    try:
        return cleaned
    except Exception as e:
        logger.warning("Grammar rewrite failed; using cleaned text. (%s)", e)
        return cleaned


def _guess_ticker(text: str) -> Optional[str]:
    """
    If the text contains exactly one ticker-like token, return it.
    Zero matches → None (no ticker).
    Two or more → None (too ambiguous to pick for the user).
    """
    found = [m for m in _TICKER_RE.findall(text) if m not in _COMMON_CAPS]
    if len(found) == 1:
        return found[0]
    return None


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    """
    True if any keyword from the list appears in the query (case-insensitive).
    """
    lower = text.lower()
    return any(word in lower for word in words)


def _infer_intent(cleaned: str, attachment_count: int) -> dict:
    """
    Rule-based sense of the query.

    Uses:
    - words in the query
    - whether the orchestrator said files were attached

    Returns a small dict. analyze_query() copies these fields into the final result so the rest of the pipeline has one stable shape.
    """
    try:
        has_file = attachment_count > 0
        wants_summary = _contains_any(cleaned, SUMMARIZE_KEYWORDS)
        wants_insight = _contains_any(cleaned, INSIGHT_KEYWORDS)
        mentions_doc = _contains_any(cleaned, DOCUMENT_KEYWORDS)
        mentions_finance = _contains_any(cleaned, FINANCE_KEYWORDS)
        ticker = _guess_ticker(cleaned)

        # File + "summarize" → recap the attachment.
        if has_file and wants_summary and not wants_insight:
            return {
                "intent": INTENT_SUMMARIZE_DOCUMENT,
                "in_scope": True,
                "needs_file": True,
                "ticker": ticker,
                "user_message": "We read this as: summarize the attached document.",
                "sense_for_model": "Summarize the attached document using only extracted content.",
            }

        # File + insights / analysis / "this document" → insights on the attachment.
        if has_file and (wants_insight or wants_summary or mentions_doc):
            return {
                "intent": INTENT_INSIGHTS_ON_DOCUMENT,
                "in_scope": True,
                "needs_file": True,
                "ticker": ticker,
                "user_message": "We read this as: insights on the attached document.",
                "sense_for_model": "Give finance insights from the attached document only.",
            }

        # Sounds like a file request, but nothing was attached.
        if not has_file and (mentions_doc or wants_summary) and not ticker:
            return {
                "intent": INTENT_UNCLEAR,
                "in_scope": True,
                "needs_file": True,
                "ticker": None,
                "user_message": (
                    "This looks like a document request, but no file was attached. "
                    "Upload a file or name a company."
                ),
                "sense_for_model": "Document-style request without a file.",
            }

        # Ticker or finance words → company / general finance question.
        if ticker or mentions_finance or wants_insight:
            return {
                "intent": INTENT_COMPANY_INSIGHT if ticker else INTENT_OTHER_FINANCE,
                "in_scope": True,
                "needs_file": False,
                "ticker": ticker,
                "user_message": (
                    f"We read this as a finance question"
                    f"{f' about {ticker}' if ticker else ''}."
                ),
                "sense_for_model": (
                    f"Finance question. Ticker={ticker or 'unknown'}. Query: {cleaned}"
                ),
            }

        # Nothing matched — do not send this to the prediction model.
        return {
            "intent": INTENT_OUT_OF_SCOPE,
            "in_scope": False,
            "needs_file": False,
            "ticker": None,
            "user_message": (
                "We could not treat this as a finance or document question. "
                "If it is finance-related, please rephrase."
            ),
            "sense_for_model": "Out of scope.",
        }
    except QueryAnalysisError:
        raise
    except Exception as e:
        # Sense-step bug or future model failure lands here.
        raise QueryAnalysisError(f"Could not make sense of the query: {e}") from e


def analyze_query(raw_query: Any, attachment_count: int = 0) -> dict[str, Any]:
    """
    Public entry point.
    attachment_count is decided by the orchestrator (it owns files).
    This function only needs the number, not the paths.
    """
    if not isinstance(attachment_count, int):
        raise QueryAnalysisError("attachment_count must be an integer.")
    if attachment_count < 0:
        raise QueryAnalysisError("attachment_count cannot be negative.")
    if attachment_count > MAX_ATTACHMENTS:
        raise QueryAnalysisError(f"Too many attachments (max {MAX_ATTACHMENTS}).")

    original = _require_text(raw_query)
    cleaned = _clean(original)

    if not cleaned:
        raise QueryAnalysisError("Query is empty.")
    if len(cleaned) < MIN_QUERY_CHARS:
        raise QueryAnalysisError(f"Query is too short (min {MIN_QUERY_CHARS} characters).")
    if len(original) > MAX_QUERY_CHARS or len(cleaned) > MAX_QUERY_CHARS:
        raise QueryAnalysisError(f"Query is too long (max {MAX_QUERY_CHARS} characters).")

    converted = _apply_grammar(cleaned)
    inferred = _infer_intent(converted, attachment_count)

    # One stable dict for save + prediction + terminal printing.
    return {
        "raw_query": original.strip("\n"),
        "converted_query": converted,
        "in_scope": inferred["in_scope"],
        "intent": inferred["intent"],
        "needs_file": inferred["needs_file"],
        "attachment_count": attachment_count,
        "ticker": inferred["ticker"],
        "company_guess": None,  # filled later if we add a name lookup
        "user_message": inferred["user_message"],
        "sense_for_model": inferred["sense_for_model"],
        "analysis_ok": True,
    }