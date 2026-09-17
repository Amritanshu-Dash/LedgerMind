# LedgerMind — Phase 1 + Cache DB verification pass

**Read `CLAUDE.md` first if you haven't.**

Goal: confirm everything built so far (the input section + cache DB)
actually works, before Amrit starts building the brain/router on top of
it. This is a verification pass, not a redesign — fix genuine bugs you
find along the way (two are already known, see Step 1), but if you hit
something that looks like a real architecture or scope question rather
than a clear bug, stop and ask instead of deciding on your own.

Work through the steps in order. After each step, report pass/fail and
what (if anything) you changed, before moving to the next one. At the
end, give one overall verdict: is the base solid enough to build phase 2
on top of, or not yet (and why).

---

## Step 0 — Environment check

Before running anything, confirm:
- `.env` has `CACHE_DB_HOST/PORT/NAME/USER/PASSWORD` and
  `CACHE_DB_ADMIN_PASSWORD` set (see
  `src/database/cache_database/database_handlers/_00_connection.py` for
  the exact required variables).
- Postgres is running and the `cache_db` database exists with migrations
  0001–0005 applied, in order (`src/database/cache_database/database_migrations/`).
  If you're not sure they're applied, check for a `schema_migrations`
  table and see which versions are recorded (note: `0001_init.sql` won't
  have a row there — it's a raw pg_dump of the initial schema, not a
  tracked migration — that's expected, not a bug).
- `clamscan --version` works (ClamAV installed and on PATH).
- `vision_models/` and `text_models/` contain the GGUF files listed in
  `requirements.models.txt` — only needed for Steps 5 and 7; skip those
  specific checks (and say so in your report) if the weights aren't
  downloaded yet, don't block everything else on it.

Report what's present/missing before continuing.

## Step 1 — Fix two known-broken self-tests

Both are stale after `unique_query_id` became a required field (added in
migration 0004/0005):

1. `src/database/cache_database/database_handlers/_01_attachments_cache_repository.py`
   — the `__main__` block calls `insert_cache_document(...)` without
   `unique_query_id` or `comments`. Update the call to pass both (you'll
   need a real `unique_query_id` — insert a throwaway `cache_queries` row
   first via `insert_cache_query`, or use `insert_cache_query`'s own
   quick-test pattern).
2. `src/input/file_input/_01_orchestrator.py` — the `__main__` block
   calls `process_file(...)` without `unique_query_id`. Same fix.

These are just broken test scaffolding, not pipeline bugs — the real
`process_file` call in `_01_intake.py` already passes `unique_query_id`
correctly.

## Step 2 — Run each module's own quick test

Each file below has an `if __name__ == "__main__":` block. Run them in
this order (matches pipeline order) and report pass/fail for each:

- `src/input/file_input/_00_constants.py`
- `src/input/file_input/_02_input.py` (edit its hardcoded test path to a
  real local file or URL first)
- `src/input/file_input/_03_scanner.py`
- `src/input/file_input/_04_extractor.py`
- `src/input/file_input/_05_vision_model_llava.py` (needs model weights
  — see Step 0)
- `src/input/file_input/_01_orchestrator.py` (after Step 1's fix; edit
  its hardcoded test path)
- `src/database/cache_database/database_handlers/_00_connection.py`
- `src/database/cache_database/database_handlers/_02_query_cache_repository.py`
  (no `__main__` block — write a throwaway insert+read instead)
- `src/database/cache_database/database_handlers/_01_attachments_cache_repository.py`
  (after Step 1's fix)
- `src/input/query_input/_02_query_analysis.py` (no `__main__` block —
  try a few sample queries covering each intent: a summarize-with-file
  query, an insights-with-file query, a ticker-only query with no file,
  a clearly out-of-scope query, and a document-style query with no file
  attached — confirm each lands on the intent you'd expect from reading
  `_infer_intent`)
- `src/input/query_input/_01_orchestrator.py`

## Step 3 — Structural/security checks (logic-only, no model needed)

- SSRF: call `_assert_url_is_safe()` (in `_02_input.py`) with a URL that
  resolves to `127.0.0.1` or `169.254.169.254` — confirm it raises
  `SuspiciousURLError`.
- Magic-byte mismatch: rename a `.png` to `.pdf` and run it through
  `scan_file()` — confirm it raises `SuspiciousFileError`, not a silent
  pass.
- Zip-based Office file: run a normal `.docx` through `scan_file()` —
  confirm it passes. (Don't spend time trying to craft an actual zip
  bomb/malicious macro for this pass — just confirm normal files pass
  cleanly.)
- PDF: run a normal PDF through `scan_file()` — confirm it passes.

## Step 4 — End-to-end file pipeline

Using a real sample file (a small PDF or DOCX with some real financial
content — an SEC filing works well, see `download_sec_filings.py`):

1. Call `process_query()` with a query that needs a file (e.g. "summarize
   this document") and the file's path as an attachment, to get a real
   `unique_query_id`.
2. Call `process_file()` with that file, `unique_query_id`, and a
   company name/ticker.
3. Confirm: the file is scanned and extracted without error, a row lands
   in `cache_data` with `data_review_status = 'system-ingested'` and the
   fixed system comment, `unique_query_id` correctly links back to the
   `cache_queries` row from step 1, and the extracted text looks sane for
   the document you used.

## Step 5 — DB constraint checks

These are enforced by Postgres itself (see migration 0002), not just
application code — worth confirming they actually hold at the DB level,
using the functions in `_01_attachments_cache_repository.py`:

- Call `delete_document()` on a row that is NOT `rejected` — confirm it
  raises `DeleteNotAllowedError`.
- Call `update_review_status()` with a wrong/empty admin password —
  confirm `IncorrectAdminPasswordError`.
- Call `update_review_status()` with the right password but no
  `reviewed_by` — confirm `MissingReviewerError`.
- Call `update_review_status()` with no `comments` — confirm
  `MissingCommentError`.
- Call `update_review_status()` trying to set status to
  `'system-ingested'` — confirm `SystemStatusNotAllowedError`.
- Approve a document, then reject it, then delete it — confirm the full
  happy path works and `updated_at`/`reviewed_at` actually change (the
  `handle_cache_data_update` trigger).

## Step 6 — Query pipeline end-to-end

Run `process_query()` (via `src/input/_01_intake.py` or directly) with a
few different queries and confirm the routing matches what you'd expect
from `_infer_intent` in `_02_query_analysis.py`:
- out-of-scope query → skipped, nothing saved
- finance question, no file, no ticker → saved, `other_finance`
- finance question with a ticker → saved, `company_insight`
- "summarize this" with a file attached → saved, `summarize_document`

## Step 7 (optional, only if model weights are present) — Vision model

Run `analyze_images()` on one real financial-looking image and one
clearly-unrelated image (a photo of anything non-financial). Confirm the
financial one gets accepted with extracted text, and the unrelated one
gets rejected with a `REJECT:`-derived reason. This step is slow (model
load + inference) — fine to skip in a quick pass and just note it wasn't
run.

---

## Known open items — don't "fix" these unless asked, just don't be
## surprised by them if you notice them while testing:

- `.txt`/`.csv` files skip the magic-byte content check by design (text
  files have no real magic number) — ClamAV is the only structural gate
  for those two extensions.
- The zip-bomb check in `_03_scanner.py` reads declared size metadata
  from the zip's central directory rather than actually decompressing —
  a known limitation of pre-decompression bomb detection, not something
  to redesign in this pass.
- The PDF active-content check is a raw-byte regex — it won't catch
  `/JavaScript` etc. hidden inside a compressed PDF object stream. Also
  known, also not in scope for this pass.
- The SSRF check has an acknowledged DNS-rebinding gap (documented in
  `_02_input.py`'s own module docstring) — the hostname is re-resolved
  between the safety check and the actual request.

These are real, but they're pre-existing and already understood —
flagging them again isn't useful; only escalate if you find something
*beyond* what's listed here.
