"""
_01_cache_repository.py
------------------------
All the actual read/write operations against the cache_data table.

Location:
    src/database/cache_database/database_handlers/_01_cache_repository.py

Access rules (project decision):
- Reading data → no extra password needed
- Changing data (approve / reject / delete / promote) → requires the admin password

Important:
This admin password is only a soft local protection.
It is NOT real multi-user security. Later we can upgrade to real Postgres roles.

Two rules are enforced by the DATABASE itself (see migration 0002):
1. You can only delete a row when its status is 'rejected'
2. Any row that is not in a system-only state must have a non-empty reviewed_by when required

The checks in this file are just a friendly early warning.
The database is the final authority.
"""

import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.types.json import Json

from ._00_connection import get_connection, get_admin_password

logger = logging.getLogger(__name__)

# -------------------------------------------------
# Statuses
# -------------------------------------------------
# system-ingested → only the extraction code can set this (on first insert)
# in_progress     → user is reviewing / working on the document
# approved        → user approved it
# rejected        → user rejected it
VALID_REVIEW_STATUSES = {"system-ingested", "in_progress", "approved", "rejected"}

# Users are never allowed to set this status
SYSTEM_ONLY_STATUS = "system-ingested"

# These match the real column limits in the database
MAX_COMPANY_NAME_LENGTH = 150
MAX_COMPANY_STOCK_NAME_LENGTH = 50

# Default comment used when the system first inserts a document
SYSTEM_INGEST_COMMENT = "System extracted and ingested the document data."


# ==============================
# Custom Exceptions
# ==============================

class IncorrectAdminPasswordError(Exception):
    """Wrong or missing admin password was given for a protected action."""
    pass


class DocumentNotFoundError(Exception):
    """The document id does not exist in the table."""
    pass


class InvalidStatusError(Exception):
    """Someone tried to use a status value that is not allowed."""
    pass


class MissingReviewerError(Exception):
    """Tried to approve or reject a document without giving a reviewer name."""
    pass


class InvalidDocumentDataError(Exception):
    """Data given to insert is invalid (empty, too long, or not JSON-serializable)."""
    pass


class InvalidDocumentIdError(Exception):
    """document_id is not a positive integer."""
    pass


class CacheDataOperationError(Exception):
    """
    A database operation failed for a reason that is NOT a connection problem and is not one of the more specific errors above.
    This stops the error from being wrongly reported as "lost connection".
    """
    pass


class StatusChangeConflictError(Exception):
    """
    Could not change the review status because of the main_db_status constraint. 
    This can mean either:
    - the document is currently being promoted ('requested'), or
    - it has already been fully confirmed in the main DB ('accepted'/'rejected') and can no longer be changed through this path.
    """
    pass


class DeleteNotAllowedError(Exception):
    """
    Tried to delete a document that is not in 'rejected' status.
    The database trigger blocks this, and we turn it into a clear error.
    """
    pass


class MissingCommentError(Exception):
    """
    Tried to change a document's status without providing a comment.
    Comments are required for every user-driven status change.
    """
    pass


class SystemStatusNotAllowedError(Exception):
    """
    A user tried to set the status to 'system-ingested'.
    Only the extraction code is allowed to use this status.
    """
    pass


# ==============================
# Small helper functions
# ==============================

def _require_admin_password(password: Optional[str]) -> None:
    """
    Checks the admin password.
    Uses constant-time comparison so timing attacks are harder.
    """
    expected = get_admin_password()
    if not secrets.compare_digest(password or "", expected):
        raise IncorrectAdminPasswordError("Incorrect admin password for this action.")


def _require_valid_document_id(document_id: Any) -> int:
    """
    Makes sure document_id is a real positive integer.
    Stops bad values (None, string, 0, negative) early with a clear message.
    """
    if not isinstance(document_id, int) or isinstance(document_id, bool) or document_id <= 0:
        raise InvalidDocumentIdError(
            f"document_id must be a positive integer. Got: {document_id!r}"
        )
    return document_id


# ==============================
# Result type
# ==============================

@dataclass
class CacheDocument:
    """One row from cache_data, turned into a nice Python object."""
    id: int
    company_name: str
    company_stock_name: str
    extracted_data: Dict[str, Any]
    file_path: str
    original_filename: str
    data_review_status: str
    reviewed_by: Optional[str]
    reviewed_at: Any
    main_db_status: Optional[str]
    main_db_requested_at: Any
    main_db_resolved_at: Any
    comments: Optional[str]
    created_at: Any
    updated_at: Any


# Columns we always select, in this exact order
_SELECT_COLUMNS = (
    "id, company_name, company_stock_name, extracted_data, file_path, original_filename, "
    "data_review_status, reviewed_by, reviewed_at, "
    "main_db_status, main_db_requested_at, main_db_resolved_at, "
    "comments, created_at, updated_at"
)


def _row_to_document(row: dict) -> CacheDocument:
    """Turns a database row (dict) into a CacheDocument object."""
    return CacheDocument(
        id=row["id"],
        company_name=row["company_name"],
        company_stock_name=row["company_stock_name"],
        extracted_data=row["extracted_data"] or {},
        file_path=row["file_path"],
        original_filename=row["original_filename"],
        data_review_status=row["data_review_status"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        main_db_status=row["main_db_status"],
        main_db_requested_at=row["main_db_requested_at"],
        main_db_resolved_at=row["main_db_resolved_at"],
        comments=row["comments"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ==============================
# INSERT (no admin password needed)
# ==============================

def insert_cache_document(
    company_name: str,
    company_stock_name: str,
    extracted_data: Dict[str, Any],
    file_path: str,
    original_filename: str,
) -> int:
    """
    Inserts a newly extracted document.

    This is the ONLY place that is allowed to use the status 'system-ingested'.
    A fixed system comment is also written so we always know this row was created by the extraction code.
    """
    # Clean the strings first
    company_name = (company_name or "").strip()
    company_stock_name = (company_stock_name or "").strip()
    file_path = (file_path or "").strip()
    original_filename = (original_filename or "").strip()

    # Basic validation
    if not company_name:
        raise InvalidDocumentDataError("company_name cannot be empty.")
    if len(company_name) > MAX_COMPANY_NAME_LENGTH:
        raise InvalidDocumentDataError(
            f"company_name is {len(company_name)} characters long. "
            f"Maximum allowed is {MAX_COMPANY_NAME_LENGTH}."
        )

    if not company_stock_name:
        raise InvalidDocumentDataError("company_stock_name cannot be empty.")
    if len(company_stock_name) > MAX_COMPANY_STOCK_NAME_LENGTH:
        raise InvalidDocumentDataError(
            f"company_stock_name is {len(company_stock_name)} characters long. "
            f"Maximum allowed is {MAX_COMPANY_STOCK_NAME_LENGTH}."
        )

    if not file_path:
        raise InvalidDocumentDataError("file_path cannot be empty.")

    if not original_filename:
        raise InvalidDocumentDataError("original_filename cannot be empty.")

    # Make sure the data can actually be turned into JSON
    try:
        json.dumps(extracted_data)
    except TypeError as e:
        raise InvalidDocumentDataError(
            f"extracted_data contains values that cannot be converted to JSON: {e}"
        ) from e

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO cache_data (
                        company_name,
                        company_stock_name,
                        extracted_data,
                        file_path,
                        original_filename,
                        data_review_status,
                        comments
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        company_name,
                        company_stock_name,
                        Json(extracted_data),
                        file_path,
                        original_filename,
                        SYSTEM_ONLY_STATUS,          # only the system can set this
                        SYSTEM_INGEST_COMMENT,       # clear system comment
                    ),
                )
            except psycopg.Error as e:
                raise CacheDataOperationError(f"Failed to insert cache document: {e}") from e

            new_id = cur.fetchone()["id"]

    logger.info(
        f"Inserted cache document {new_id} for {company_name} "
        f"with status '{SYSTEM_ONLY_STATUS}' ({file_path})"
    )
    return new_id


# ==============================
# READ functions (no password needed)
# ==============================

def get_document(document_id: int) -> CacheDocument:
    """Fetch one document by its id."""
    document_id = _require_valid_document_id(document_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM cache_data WHERE id = %s;",
                    (document_id,),
                )
                row = cur.fetchone()
            except psycopg.Error as e:
                raise CacheDataOperationError(
                    f"Failed to fetch cache document {document_id}: {e}"
                ) from e

    if row is None:
        raise DocumentNotFoundError(f"No cache document with id {document_id}")

    return _row_to_document(row)


def list_documents(status: Optional[str] = None) -> List[CacheDocument]:
    """
    List documents.
    If status is given, only return documents with that data_review_status.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                if status is not None:
                    if status not in VALID_REVIEW_STATUSES:
                        raise InvalidStatusError(
                            f"'{status}' is not a valid status. "
                            f"Allowed values: {sorted(VALID_REVIEW_STATUSES)}"
                        )
                    cur.execute(
                        f"SELECT {_SELECT_COLUMNS} FROM cache_data "
                        f"WHERE data_review_status = %s ORDER BY created_at DESC;",
                        (status,),
                    )
                else:
                    cur.execute(
                        f"SELECT {_SELECT_COLUMNS} FROM cache_data ORDER BY created_at DESC;"
                    )
                rows = cur.fetchall()
            except psycopg.Error as e:
                raise CacheDataOperationError(f"Failed to list cache documents: {e}") from e

    return [_row_to_document(r) for r in rows]


# ==============================
# WRITE functions (admin password required)
# ==============================

def update_review_status(
    document_id: int,
    new_status: str,
    reviewed_by: Optional[str],
    admin_password: str,
    comments: str,
) -> CacheDocument:
    """
    Changes the data_review_status of a document.

    Rules:
    - Admin password is required.
    - Users are never allowed to set status to 'system-ingested'.
    - A comment is required for every user-driven status change.
    - reviewed_by is required when moving to 'approved' or 'rejected'.
    """
    # 1. Authenticate first
    _require_admin_password(admin_password)

    # 2. Block users from setting the system-only status
    if new_status == SYSTEM_ONLY_STATUS:
        raise SystemStatusNotAllowedError(
            f"Status '{SYSTEM_ONLY_STATUS}' can only be set by the system "
            "during the initial insert. Users cannot set this status."
        )

    # 3. Basic validation
    if new_status not in VALID_REVIEW_STATUSES:
        raise InvalidStatusError(
            f"'{new_status}' is not a valid status. "
            f"Allowed values: {sorted(VALID_REVIEW_STATUSES)}"
        )

    document_id = _require_valid_document_id(document_id)

    # 4. Comment is required for every user status change
    comments = (comments or "").strip()
    if not comments:
        raise MissingCommentError(
            "comments is required whenever a user changes the status."
        )

    # 5. Reviewer is required when approving or rejecting
    if new_status in ("approved", "rejected") and not (reviewed_by and reviewed_by.strip()):
        raise MissingReviewerError(
            "reviewed_by is required when setting status to 'approved' or 'rejected'."
        )

    reviewed_by = reviewed_by.strip() if reviewed_by else reviewed_by

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    UPDATE cache_data
                    SET
                        data_review_status = %s,
                        reviewed_by = %s,
                        comments = %s
                    WHERE id = %s
                    RETURNING *;
                    """,
                    (new_status, reviewed_by, comments, document_id),
                )
            except psycopg.errors.CheckViolation as e:
                raise StatusChangeConflictError(
                    "This document's status cannot be changed right now. "
                    "It is either currently being sent to the main DB (try again shortly) "
                    "or has already been permanently confirmed there "
                    "(in which case it can no longer be changed)."
                ) from e
            except psycopg.Error as e:
                raise CacheDataOperationError(
                    f"Failed to update review status for document {document_id}: {e}"
                ) from e

            row = cur.fetchone()
            if row is None:
                raise DocumentNotFoundError(f"No cache document with id {document_id}")

    logger.info(
        f"Cache document {document_id} status changed to '{new_status}' by {reviewed_by}"
    )
    return _row_to_document(row)


def delete_document(document_id: int, admin_password: str) -> None:
    """
    Deletes a document.
    Only works if the document is currently in 'rejected' status.
    The database trigger enforces this rule.
    """
    _require_admin_password(admin_password)
    document_id = _require_valid_document_id(document_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("DELETE FROM cache_data WHERE id = %s;", (document_id,))
            except psycopg.errors.RaiseException as e:
                raise DeleteNotAllowedError(
                    f"Cannot delete document {document_id}. "
                    "Only documents with status 'rejected' can be deleted."
                ) from e
            except psycopg.Error as e:
                raise CacheDataOperationError(
                    f"Failed to delete cache document {document_id}: {e}"
                ) from e

            if cur.rowcount == 0:
                raise DocumentNotFoundError(f"No cache document with id {document_id}")

    logger.info(f"Cache document {document_id} deleted.")


def promote_approved_documents(admin_password: str) -> Dict[str, List[Any]]:
    """
    Finds every approved document that still needs to be sent to the main DB
    and moves it through the two steps: 'requested' → 'accepted'.

    Also picks up rows that got stuck in 'requested' from a previous crash
    (self-healing).

    Returns:
        {
            "promoted": [list of ids that succeeded],
            "skipped":  [(id, reason), ...]
        }
    """
    _require_admin_password(admin_password)

    promoted_ids: List[int] = []
    skipped: List[Any] = []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SELECT_COLUMNS} FROM cache_data "
                f"WHERE data_review_status = 'approved' "
                f"AND (main_db_status IS NULL OR main_db_status = 'requested');"
            )
            rows = cur.fetchall()

        for row in rows:
            doc = _row_to_document(row)

            # Step 1: mark as 'requested'
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE cache_data
                        SET main_db_status = 'requested',
                            main_db_requested_at = now()
                        WHERE id = %s;
                        """,
                        (doc.id,),
                    )
            except psycopg.errors.CheckViolation as e:
                logger.warning(f"Skipping document {doc.id}: no longer eligible ({e})")
                skipped.append((doc.id, "no longer approved"))
                continue

            # ---- PLACEHOLDER for the real main-DB call ----
            print(f"[main DB placeholder] Would send document {doc.id} ({doc.company_name})")
            # ------------------------------------------------

            # Step 2: mark as 'accepted'
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE cache_data
                        SET main_db_status = 'accepted',
                            main_db_resolved_at = now()
                        WHERE id = %s;
                        """,
                        (doc.id,),
                    )
            except psycopg.errors.CheckViolation as e:
                logger.warning(
                    f"Document {doc.id}: status changed during promotion, left as 'requested'"
                )
                skipped.append((doc.id, "status changed mid-promotion"))
                continue

            promoted_ids.append(doc.id)
            logger.info(f"Promoted cache document {doc.id}")

    return {"promoted": promoted_ids, "skipped": skipped}


# ==============================
# Quick self-test
# ==============================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("Testing cache_repository.py...")
    print("=" * 60)

    new_id = insert_cache_document(
        company_name="Test Company Inc",
        company_stock_name="TEST",
        extracted_data={
            "text": "Total due: $123.45",
            "images_found": 0,
            "images_rejected": 0,
            "rejection_reasons": [],
        },
        file_path="/tmp/test_document.txt",
        original_filename="test_document.txt",
    )
    print(f"✅ Inserted test document: {new_id}")

    doc = get_document(new_id)
    print(f"✅ Status after insert = {doc.data_review_status}")
    print(f"✅ System comment      = {doc.comments}")

    admin_pw = get_admin_password()

    # Move it to in_progress
    doc = update_review_status(
        new_id,
        "in_progress",
        reviewed_by="Amritanshu",
        admin_password=admin_pw,
        comments="Started reviewing the extracted data.",
    )
    print(f"✅ Status updated to '{doc.data_review_status}'")

    # Reject it
    doc = update_review_status(
        new_id,
        "rejected",
        reviewed_by="Amritanshu",
        admin_password=admin_pw,
        comments="Test rejection — verifying the new status rules.",
    )
    print(f"✅ Status updated to '{doc.data_review_status}' by {doc.reviewed_by}")

    delete_document(new_id, admin_password=admin_pw)
    print(f"✅ Deleted test document {new_id}")