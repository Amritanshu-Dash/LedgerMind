# LedgerMind — Phase 1 production-readiness review

Written after the Sept 17 testing pass (all 7 steps clean — see git history
around that date for the fixes that came out of it). This is a different
kind of pass: not "does it work" but "is this the right way to have built
it, given the actual constraints" — M1 16GB RAM, no budget for paid/hosted
APIs, solo developer, and financial documents as the subject matter (so
privacy and correctness both matter more than in a toy project).

Read this yourself first. Nothing here should be handed to Claude Code to
implement blindly — each section ends with a recommendation and a reason,
and some of them are genuinely "your call," not obvious fixes.

---

## 1. Tool/library choices — is each one actually the right fit?

### ClamAV (malware scanning) — keep it

There is no better free, local, script-drivable antivirus for macOS.
Commercial engines are either paid or GUI-only (not built for headless
`clamscan`-style invocation); cloud scanners (VirusTotal etc.) cost money
at volume and mean uploading a user's financial documents to a third
party — a worse privacy trade than the problem you'd be solving. ClamAV
is the standard choice here, not a placeholder.

What's actually worth fixing is not ClamAV itself but the layers around
it (see Section 3 — two of them have real, closeable gaps).

### LLaVA 1.6 Mistral 7B (Q4_K_M) for vision — keep as default, but the
### triage logic matters more than the model choice

Your own framing was right: "the vision model should only do what this
pipeline actually needs it to do." Good news — the pipeline mostly
already reflects that:

- `_04_extractor.py`'s `_page_has_complex_layout()` already filters which
  PDF pages even get rendered and sent to the model, instead of routing
  every page through it. That's the real lever for cost/RAM control, more
  than which model you pick.
- The "vision model switch" comment block in `_04_extractor.py` already
  has a Moondream variant stubbed in (commented out) — meaning swapping
  models is already cheap in this codebase, by design. That's worth
  knowing: you don't need to get this choice "perfectly right" now,
  because the architecture already treats it as swappable.

On sizing: 7B at Q4 is already using roughly 4GB of your 16GB just for
weights, before macOS, Postgres, and everything else. A bigger model
(13B+, or a heavier VLM) risks real memory pressure on this machine — not
a "might be slightly slower" risk, an actual swap/OOM risk. A smaller
model (Moondream2-class, ~2B) would reduce that pressure and could be
worth trying specifically for the *inference* cost, but would likely
trade off some transcription accuracy on dense tables. Given the model is
already swappable with one line, this is a genuine experiment worth
running later against real documents — not a decision to make blind now.

**Recommendation:** don't switch yet. If phase 2 ever feels memory-tight,
try the already-stubbed Moondream path and compare real output quality on
a handful of real filings before deciding — you have the infrastructure
to A/B this cheaply.

### Everything else (psycopg3, pymupdf, python-docx, pandas, requests)

Standard, correct choices for each job — no better free alternative for
any of them. Not reviewed further; nothing to second-guess here.

---

## 2. Sequential vs. parallel — where it matters and where it doesn't (yet)

**Today:** `process_file()` is already a straight sequential chain — scan,
then extract (which may call the vision model), then DB insert. Nothing
runs concurrently within one file's processing, so the "Postgres and the
vision model fighting over RAM" scenario isn't actually happening in the
current pipeline. Postgres connections are opened briefly per call (via
`get_connection()`) and closed immediately after — not held open while
the vision model runs.

**Where it will matter:** phase 2's router, exactly as you described —
one query potentially pulling from the attached document, live news, and
the main DB at once. Your reasoning (accept "usually fast, occasionally a
minute" over the risk of memory contention, for a solo-user app) is sound
and matches how you should default the router: sequential unless a
specific path clearly benefits enough from speed to justify the RAM risk.
This isn't a one-size answer — some combinations (a fast news API call +
a main-DB lookup, both light) might be totally fine in parallel; anything
touching the vision model probably shouldn't run alongside anything else
memory-heavy.

**One real gap worth fixing before phase 2 needs it:** the vision model
worker (`_ModelWorkerManager` in `_05_vision_model_llava.py`) is built
assuming one caller at a time. `run_inference()` puts a request on a
shared queue and waits for a response matching its own request id — but
if two callers call it *concurrently* (not two separate files processed
one after another, but genuinely at the same moment, e.g. from two
threads), one can end up consuming and discarding the other's real
response, forcing an avoidable retry. Not broken today, because nothing
in the current pipeline calls it concurrently. Worth addressing (a lock
around `run_inference()`, or a small worker pool) before phase 2
introduces anything that could call it from more than one place at once.

---

## 3. Security — what's solid, what's genuinely open

Carried over from the earlier full-codebase read, re-prioritized now that
the base is tested and stable:

**Worth fixing (real, closeable gaps):**
- **Zip-bomb check trusts declared metadata, not real decompression**
  (`_03_scanner.py`, `_check_zip_safety`). A crafted `.docx`/`.xlsx` could
  lie about its own declared size in the zip header and pass this check,
  then actually bomb when `python-docx`/`pandas` really reads it later.
  Fix: decompress with a running size cap instead of trusting the header
  fields.
- **PDF active-content check is a raw-byte regex** (`_check_pdf_safety`).
  Won't catch `/JavaScript` etc. hidden inside a compressed PDF object
  stream (common since PDF 1.5). Fix needs actual PDF object parsing
  (pymupdf can walk objects), not a bigger regex.

**Acceptable as-is, already understood, not worth spending time on right
now:**
- SSRF DNS-rebinding gap (`_02_input.py`) — already documented in the
  code's own docstring as a known, accepted limitation. Closing it fully
  means IP-pinning the connection, real complexity for a solo-user app
  that isn't exposed to the public internet yet.
- `.txt`/`.csv` files skipping the magic-byte check — text files don't
  have a real magic number, so this is inherent to the file type, not a
  design mistake. ClamAV is still in the path for these.
- The cache-DB admin password being a single shared soft-check, not real
  per-user auth — already called out in the code's own docstring as
  deliberate for now, correct to leave alone until there's an actual
  multi-user need.

---

## 4. Edge-case / robustness notes

The Sept 17 testing pass already found and fixed the best example of this
category: the vision model returning genuinely empty output was being
silently recorded as a successful extraction. That's fixed. Two more
patterns in the same spirit, worth being aware of (not fixed, not
necessarily *needing* a fix — flagging for your judgment):

- **`process_file()`'s `success: True` doesn't guarantee the document
  actually made it into the cache DB.** If extraction succeeds but the
  DB insert fails, `result["success"]` is still `True`, with the real
  failure tucked into a separate `cache_insert_error` field. Fine as long
  as every caller checks both fields — worth deciding whether phase 2's
  router should treat "success" as meaning "fully persisted" instead,
  since it'll be relying on cache DB rows being trustworthy.
- **Vision-model output quality is inconsistent on unusual images** (the
  synthetic receipt in this test pass returned empty output twice,
  reproducibly). The empty case is now handled correctly (rejected). A
  non-empty-but-thin response (a couple of words, not genuinely useless
  but not a real extraction either) would still be marked "accepted" —
  there's no quality floor beyond "not literally blank." Worth deciding
  later whether the router should treat "accepted" as "definitely has
  real content" or "probably has content, worth a sanity check."

---

## Bottom line

Nothing here says the architecture is wrong. The choices already made
(ClamAV, LLaVA, sequential-by-default processing, layered scanning) are
the right ones for this project's actual constraints — this review didn't
turn up a case where a different tool would clearly be better. The real
value is the two closeable security gaps (Section 3) and the one
concurrency risk worth fixing before phase 2 can trigger it (Section 2).
Everything else here is context to carry into phase 2's design, not a
todo list.
