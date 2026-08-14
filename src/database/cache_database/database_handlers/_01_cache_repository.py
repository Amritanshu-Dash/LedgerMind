"""
_01_cache_repository.py
------------------------
All the actual read/write operations against cache_data.

Location: src/database/cache_database/database_handlers/_01_cache_repository.py

Access model, per project decision:
- Read functions (get, list/search) need nothing beyond a normal database
  connection — anyone with DB access can look. No extra password.
- Write functions that change state — approve/reject, delete, promote to
  the main DB — require a separate admin action password, checked here
  in Python, on top of the normal DB connection.

Honest limitation, stated rather than hidden: this admin password is a
soft guard appropriate for a solo local project, not real per-user
authentication. A stronger version would use real Postgres roles — a
reasonable future upgrade, not built now.

Two rules genuinely NOT just trusted to this file, enforced by the
database itself (see migrations/0002_cache_data_guardrails.sql):
- A row can only be deleted while data_review_status = 'rejected'.
- Any row that isn't 'pending' must have a non-empty reviewed_by.
This file's own checks for those two rules are a fast, friendly first
line of defense; the database constraints/triggers are the real
guarantee, and will refuse the operation even if this file's checks were
somehow bypassed.
"""

import json                                       # validates extracted_data is JSON-serializable before sending it
import logging                                    # structured logging instead of print()
import secrets                                    # secrets.compare_digest() — constant-time string comparison,
                                                   # so checking the admin password doesn't leak timing information
                                                   # an attacker could theoretically use to guess it character by
                                                   # character. Low real-world risk for a solo local project, but
                                                   # a one-line fix with no downside, worth doing correctly.
from dataclasses import dataclass                 # lightweight structured result object
from typing import Any, Dict, List, Optional       # type hints so signatures are self-documenting

import psycopg                                    # needed for psycopg's own error types

from ._00_connection import get_connection, get_admin_password

logger = logging.getLogger(__name__)              # module-level logger tagged with this file's name

VALID_REVIEW_STATUSES = {"pending", "approved", "rejected"}
VALID_MAIN_DB_STATUSES = {"requested", "accepted", "rejected"}

# Match the real VARCHAR limits from migrations/0001 exactly — checked
# here BEFORE ever sending to Postgres, so a too-long name fails with a
# clear message instead of a raw database error.
MAX_COMPANY_NAME_LENGTH = 150
MAX_COMPANY_STOCK_NAME_LENGTH = 50


# ==============================
# Custom Exceptions
# ==============================

class IncorrectAdminPasswordError(Exception):
    """Raised when a mutating action is attempted with the wrong (or missing) admin password."""
    pass


class DocumentNotFoundError(Exception):
    """Raised when an operation references a document id that doesn't exist."""
    pass


class InvalidStatusError(Exception):
    """Raised when asked to set or filter by a status outside the allowed set."""
    pass


class MissingReviewerError(Exception):
    """Raised when trying to set a non-pending status without naming a reviewer —
    mirrors the database's own reviewer_required_when_reviewed constraint,
    but catches the mistake here with a clearer message before it ever
    reaches Postgres."""
    pass


class InvalidDocumentDataError(Exception):
    """Raised when data handed to insert_cache_document() is invalid before
    it's ever sent to the database — too long for its column, or not
    something that can be turned into JSON at all."""
    pass


class InvalidDocumentIdError(Exception):
    """Raised when a document_id isn't a real, positive integer — catches
    a caller mistake (None, a string, a negative number) with a clear
    message instead of a confusing 'not found' from a query that could
    never have matched anything."""
    pass


def _require_admin_password(password: Optional[str]) -> None:
    """Shared guard called at the top of every mutating function below."""
    expected = get_admin_password()  # raises RuntimeError if not configured
    # secrets.compare_digest instead of != — see the import comment above
    # for why. Needs both sides to be strings; a None password (caller
    # forgot to pass one) is treated as simply wrong, not a crash.
    if not secrets.compare_digest(password or "", expected):
        raise IncorrectAdminPasswordError("Incorrect admin password for this action.")


def _require_valid_document_id(document_id: Any) -> int:
    """Shared guard: confirms document_id is actually a positive integer
    before it's used in any query. Called at the top of every function
    that operates on a specific existing document."""
    if not isinstance(document_id, int) or isinstance(document_id, bool) or document_id <= 0:
        raise InvalidDocumentIdError(f"document_id must be a positive integer. Got: {document_id!r}")
    return document_id


# ==============================
# Result type
# ==============================

@dataclass
class CacheDocument:
    """One row from cache_data, as a structured result instead of a raw tuple."""
    id: int
    company_name: str
    company_stock_name: str
    extracted_data: Dict[str, Any]
    file_path: str
    original_filename: Optional[str]
    data_review_status: str
    reviewed_by: Optional[str]
    reviewed_at: Any
    main_db_status: Optional[str]
    main_db_requested_at: Any
    main_db_resolved_at: Any
    comments: Optional[str]
    created_at: Any
    updated_at: Any


# Every SELECT below asks for columns in this exact order, so _row_to_document
# only has to know the order once instead of repeating it everywhere.
_SELECT_COLUMNS = (
    "id, company_name, company_stock_name, extracted_data, file_path, original_filename, "
    "data_review_status, reviewed_by, reviewed_at, "
    "main_db_status, main_db_requested_at, main_db_resolved_at, "
    "comments, created_at, updated_at"
)


def _row_to_document(row: dict) -> CacheDocument:
    """row is a dict now (row_factory=dict_row), keyed by column name — no
    positional index to keep in sync with the SELECT column order."""
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
# Insert (no admin password required)
# ==============================

def insert_cache_document(
    company_name: str,
    company_stock_name: str,
    extracted_data: Dict[str, Any],
    file_path: str,
    original_filename: Optional[str] = None,
) -> int:
    """
    Inserts a newly-extracted document as 'pending'. No admin password —
    adding new pending data isn't the kind of action the password guard
    is meant to gate; only changing/removing existing data is.

    company_name/company_stock_name currently come from the file/folder
    name at call time (manual, per project decision) — proper structured
    extraction of these fields is future work for the analyser stage.

    extracted_data holds the FULL dict extract_content() returns —
    text, normal_text, vision_text, images_found, images_rejected,
    rejection_reasons, all of it — stored as-is in the JSONB column.

    Returns the new row's id.
    """
    if not company_name or not company_name.strip():
        raise InvalidDocumentDataError("company_name cannot be empty.")
    if len(company_name) > MAX_COMPANY_NAME_LENGTH:
        raise InvalidDocumentDataError(
            f"company_name is {len(company_name)} chars, max is {MAX_COMPANY_NAME_LENGTH}."
        )
    if not company_stock_name or not company_stock_name.strip():
        raise InvalidDocumentDataError("company_stock_name cannot be empty.")
    if len(company_stock_name) > MAX_COMPANY_STOCK_NAME_LENGTH:
        raise InvalidDocumentDataError(
            f"company_stock_name is {len(company_stock_name)} chars, max is {MAX_COMPANY_STOCK_NAME_LENGTH}."
        )

    try:
        # psycopg.types.json.Json() wraps the dict so psycopg knows to
        # serialize it as JSON for the JSONB column, rather than trying
        # to send a raw Python dict (which it can't). The actual
        # serialization normally happens lazily when the query runs — we
        # force it here first, with the plain standard-library json
        # module, purely to catch a non-serializable value (a datetime,
        # raw bytes) early with a clear message, before it ever reaches
        # psycopg or the database.
        json.dumps(extracted_data)
    except TypeError as e:
        raise InvalidDocumentDataError(f"extracted_data is not JSON-serializable: {e}") from e

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cache_data
                    (company_name, company_stock_name, extracted_data, file_path, original_filename)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    company_name,
                    company_stock_name,
                    psycopg.types.json.Json(extracted_data),
                    file_path,
                    original_filename,
                ),
            )
            new_id = cur.fetchone()["id"]  # autocommit=True already made this durable
    logger.info(f"Inserted cache document {new_id} for {company_name} ({file_path})")
    return new_id


# ==============================
# Read (no password required)
# ==============================

def get_document(document_id: int) -> CacheDocument:
    """Fetch one document by id."""
    document_id = _require_valid_document_id(document_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_SELECT_COLUMNS} FROM cache_data WHERE id = %s;", (document_id,))
            row = cur.fetchone()
    if row is None:
        raise DocumentNotFoundError(f"No cache document with id {document_id}")
    return _row_to_document(row)


def list_documents(status: Optional[str] = None) -> List[CacheDocument]:
    """List/search documents, optionally filtered by data_review_status."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if status is not None:
                if status not in VALID_REVIEW_STATUSES:
                    raise InvalidStatusError(f"'{status}' is not valid. Allowed: {sorted(VALID_REVIEW_STATUSES)}")
                cur.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM cache_data WHERE data_review_status = %s ORDER BY created_at DESC;",
                    (status,),
                )
            else:
                cur.execute(f"SELECT {_SELECT_COLUMNS} FROM cache_data ORDER BY created_at DESC;")
            rows = cur.fetchall()
    return [_row_to_document(r) for r in rows]


# ==============================
# Write (admin password required)
# ==============================

def update_review_status(
    document_id: int,
    new_status: str,
    reviewed_by: Optional[str],
    admin_password: str,
    comments: Optional[str] = None,
) -> CacheDocument:
    """
    Changes a document's data_review_status — the "data manipulation"
    the project rules specifically call out as needing the admin
    password. reviewed_by is required for anything other than 'pending' —
    checked here first for a clear error message, and enforced again by
    the database's own CHECK constraint regardless.
    """
    if new_status not in VALID_REVIEW_STATUSES:
        raise InvalidStatusError(f"'{new_status}' is not valid. Allowed: {sorted(VALID_REVIEW_STATUSES)}")
    if new_status != "pending" and not (reviewed_by and reviewed_by.strip()):
        raise MissingReviewerError("reviewed_by is required when setting status to 'approved' or 'rejected'.")
    document_id = _require_valid_document_id(document_id)
    reviewed_by = reviewed_by.strip() if reviewed_by else reviewed_by  # store cleanly, no stray whitespace
    _require_admin_password(admin_password)

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    UPDATE cache_data
                    SET data_review_status = %s, reviewed_by = %s, comments = COALESCE(%s, comments)
                    WHERE id = %s
                    RETURNING id;
                    """,
                    (new_status, reviewed_by, comments, document_id),
                )
            except psycopg.errors.CheckViolation as e:
                # Under autocommit, a failed statement simply has no
                # effect — nothing pending to roll back before the next
                # statement can run.
                raise MissingReviewerError(str(e)) from e
            result = cur.fetchone()
            if result is None:
                raise DocumentNotFoundError(f"No cache document with id {document_id}")
    logger.info(f"Cache document {document_id} data_review_status changed to '{new_status}' by {reviewed_by}")
    return get_document(document_id)


def delete_document(document_id: int, admin_password: str) -> None:
    """
    Deletes a document. Only actually succeeds if data_review_status =
    'rejected' — the database trigger enforces this regardless of what
    this function does; the check here just gives a clearer, faster
    error message for the common case.
    """
    _require_admin_password(admin_password)
    document_id = _require_valid_document_id(document_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("DELETE FROM cache_data WHERE id = %s;", (document_id,))
            except psycopg.errors.RaiseException as e:
                # This is the database TRIGGER refusing the delete — a
                # non-rejected row was targeted. Nothing was committed,
                # nothing to roll back.
                raise ValueError(str(e)) from e
            if cur.rowcount == 0:
                raise DocumentNotFoundError(f"No cache document with id {document_id}")
    logger.info(f"Cache document {document_id} deleted.")


def promote_approved_documents(admin_password: str) -> List[int]:
    """
    Finds every 'approved' document that hasn't been sent toward the main
    DB yet (main_db_status IS NULL), and moves it through the two real
    states your schema defines: 'requested' (the call is being made),
    then 'accepted' or 'rejected' (the outcome).

    The main DB doesn't exist yet, so for now this SIMULATES a successful
    call — every row goes 'requested' then 'accepted', with a placeholder
    print statement standing in for the real call. This is the ONE place
    that changes once the main DB exists: the print statement becomes a
    real call, and main_db_status gets set to 'accepted' or 'rejected'
    based on what actually happened, not hardcoded to succeed. Keeping
    the request/resolve steps separate now (rather than one combined
    update) means that seam is already in exactly the right place.

    Returns the list of document ids that were promoted.
    """
    _require_admin_password(admin_password)

    promoted_ids = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SELECT_COLUMNS} FROM cache_data "
                f"WHERE data_review_status = 'approved' AND main_db_status IS NULL;"
            )
            rows = cur.fetchall()

        for row in rows:
            doc = _row_to_document(row)

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE cache_data SET main_db_status = 'requested', main_db_requested_at = now() WHERE id = %s;",
                    (doc.id,),
                )
            # autocommit=True already made the 'requested' state durable
            # here — if the process crashed before the next line ran,
            # that fact wouldn't be lost.

            # ---- PLACEHOLDER: this is where the real main DB call goes ----
            print(f"[main DB placeholder] Would send document {doc.id} ({doc.company_name}) to the main DB.")
            # -----------------------------------------------------------------

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE cache_data SET main_db_status = 'accepted', main_db_resolved_at = now() WHERE id = %s;",
                    (doc.id,),
                )

            promoted_ids.append(doc.id)
            logger.info(f"Promoted cache document {doc.id} (placeholder — main DB not built yet).")

    return promoted_ids


# ==============================
# Quick Test
# ==============================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    print("=" * 60)
    print("Testing cache_repository.py...")
    print("=" * 60)

    new_id = insert_cache_document(
        company_name="Test Company Inc",
        company_stock_name="TEST",
        extracted_data={"text": "Total due: $123.45", "images_found": 0, "images_rejected": 0, "rejection_reasons": []},
        file_path="/tmp/test_document.txt",
        original_filename="test_document.txt",
    )
    print(f"✅ Inserted test document: {new_id}")

    doc = get_document(new_id)
    print(f"✅ Fetched it back, status = {doc.data_review_status}, main_db_status = {doc.main_db_status}")

    admin_pw = get_admin_password()
    doc = update_review_status(new_id, "rejected", reviewed_by="Amritanshu", admin_password=admin_pw)
    print(f"✅ Status updated to '{doc.data_review_status}' by {doc.reviewed_by}")

    delete_document(new_id, admin_password=admin_pw)
    print(f"✅ Deleted test document {new_id} (it was rejected, so this should succeed)")