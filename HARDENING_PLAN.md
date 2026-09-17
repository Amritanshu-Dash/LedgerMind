# LedgerMind — Phase 1 hardening pass

**Read `CLAUDE.md` and `ARCHITECTURE_REVIEW.md` first if you haven't.**

This implements the three concrete fixes `ARCHITECTURE_REVIEW.md` actually
recommended (Sections 2 and 3). It does NOT implement Section 4's two
"your call" items (the `success` flag semantics, and a vision-output
quality floor) — those are deliberately deferred to phase 2's design, not
in scope here. Don't touch them.

Same rules as the testing pass: work through the steps in order, report
what you changed after each one, and if you hit a real design question
that isn't answered below, stop and ask rather than deciding it yourself.

---

## Step 1 — Zip-bomb check: verify real decompressed size, not declared metadata

**File:** `src/input/file_input/_03_scanner.py`, `_check_zip_safety()`

**Problem:** the current check reads `entry.file_size` / `entry.compress_size`
from the zip's central directory — fields the archive itself declares,
not something actually measured. A crafted file can decompress to far
more than its own header claims.

**Fix:** for each entry, actually decompress it in bounded chunks (e.g.
via `zf.open(entry)` and reading, say, 1MB at a time) and keep a running
total of real bytes produced. Abort with `SuspiciousFileError` as soon as
that running total crosses `MAX_ZIP_UNCOMPRESSED_TOTAL_MB` — don't wait
to finish decompressing a file that's already over the limit; that
defeats the point of the check. Keep the existing entry-count check and
the per-entry compression-ratio check as-is (they're still useful, cheap
first-pass filters) — this is about making the *size* check authoritative,
not replacing the whole function.

**Acceptance:**
- Existing Step 3-style checks still pass: a real, normal `.docx` still
  scans cleanly.
- Build an actual zip bomb for testing (e.g. a file of highly-repetitive
  content that compresses to a tiny size but decompresses to hundreds of
  MB — a straightforward one to construct with the standard `zipfile`
  module) and confirm it's now rejected, and rejected *early* (bounded
  read stopping partway through, not after fully decompressing it into
  memory first).

## Step 2 — PDF active-content check: inspect actual objects, not raw bytes

**File:** `src/input/file_input/_03_scanner.py`, `_check_pdf_safety()`

**Problem:** the current check regexes the PDF's raw file bytes for
markers like `/JavaScript`. Since PDF 1.5, many producers store objects
inside compressed object streams — a marker sitting inside one of those
won't appear as plain text in the raw bytes, so this check misses it.

**Fix:** use `pymupdf` (already a dependency, imported as `fitz` in
`_04_extractor.py`) to walk the PDF's actual objects — MuPDF decompresses
object streams internally, so inspecting objects through it (rather than
the raw file) sees content the current regex can't. Check pymupdf's
actual API for the installed version before implementing (don't assume a
specific method signature from memory) — the general approach is:
iterate the document's cross-reference table and get each object's
decompressed representation, then apply the existing marker list
(`_PDF_DANGEROUS_MARKERS`) against *that*, instead of the raw file bytes.
Keep the existing raw-byte pass too if you want defense in depth — the
point is the object-level pass needs to exist, not that the byte-level
one needs to go.

**Acceptance:**
- The existing real sample PDF (`data/EX-21.1.pdf`) still passes cleanly.
- Construct a small test PDF with a `/JavaScript` action stored inside a
  compressed object stream (pymupdf itself can be used to build one, or
  hand-construct with a cross-reference stream) and confirm it's now
  caught — then confirm the *old* raw-byte-only check would have missed
  it, so the fix is actually verified, not just assumed.

## Step 3 — Vision worker: make `run_inference()` safe under concurrent calls

**File:** `src/input/file_input/_05_vision_model_llava.py`,
`_ModelWorkerManager.run_inference()`

**Problem:** two callers hitting `run_inference()` at the same moment can
each put a request on the shared queue and then both call
`self._response_q.get()` — since a response only carries its own request
id and nothing enforces one-caller-at-a-time, a caller can pull the
*other* caller's response off the queue, fail the id check, and discard
a real result it should have kept for its rightful owner.

**Fix:** add a `threading.Lock` (not a `multiprocessing.Lock` — every
current and planned caller lives in the same parent process; only the
worker itself is a separate process, and it's not calling itself) around
the request-send + response-wait sequence in `run_inference()`, so only
one call is ever mid-flight at a time. This is intentionally about
correctness, not throughput — per `ARCHITECTURE_REVIEW.md`, serializing
calls to the vision model is the *right* choice on this hardware anyway,
not a compromise.

**Acceptance:**
- Existing self-test in this file still passes.
- Write a small test that spawns two threads calling `run_inference()`
  at the same time (a mock/stub response is fine here — this is testing
  the locking behavior, not the model itself) and confirm both calls get
  their own, correct response back, with no cross-talk.

---

## When all three are done

Report a summary the same way as the testing pass: what changed, what
you verified, and one line confirming nothing outside these three files
was touched. If Step 2's exact pymupdf API turns out to need something
materially different from what's described above, that's fine — just
say what you actually used and why, don't silently paper over a mismatch.
