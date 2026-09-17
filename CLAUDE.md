# LedgerMind — project context for Claude Code

Read this before touching anything. It exists because a past Claude Code
session on this project guessed at scope it didn't have (assumed
currency/transaction handling was needed — it isn't) and that wasted time.
Don't repeat that: if something isn't covered below and isn't obvious from
the code + its docstrings, stop and ask Amrit rather than assuming.

## What this project is

A personal, solo-built financial-document analysis pipeline. Not a
transaction/accounting app — it reads financial *documents* (10-Ks, 10-Qs,
receipts, statements) and answers questions about them, combining:
attached-document content, live news/market data (not built yet), and a
main database of previously-validated company data (not built yet).

## Current status (as of this file's creation)

- **Phase 1 — input section: DONE.** Local file + URL ingestion, malware/
  structural scanning, content extraction (text + vision-routed images),
  vision model (LLaVA 1.6 via llama-cpp-python), query intent analysis.
- **Cache DB: DONE.** PostgreSQL, 5 migrations applied
  (`src/database/cache_database/database_migrations/0001`–`0005`). Two
  tables: `cache_queries` (one row per user question) and `cache_data`
  (one row per attached file, linked back to its query).
- **Phase 2 — "the brain": JUST STARTING.** A router that takes a query +
  optional attachments and decides which sources to pull from (attached
  doc / news API / main DB). Router is conditional — a "summarize this
  doc" query does NOT trigger a main-DB or news lookup. Not yet decided
  whether the router needs to be a trained classifier or can stay
  rule-based; ask before building either direction.
- **Main DB: not built yet.** Cache DB is deliberately temporary —
  approved cache rows get promoted to the main DB (after human approval,
  automated per-query-session, not per-file) and then deleted from both
  cache tables. Before storing anything new, it should be checked for
  semantic equivalence against what's already there (don't re-store the
  same fact reworded).

## Architecture conventions — follow these, don't reinvent

- Numeric filename prefixes (`_00_constants`, `_01_orchestrator`,
  `_02_...`) indicate pipeline order within a folder. Keep new files in
  that convention.
- `src/input/file_input/` and `src/input/query_input/` are two parallel
  pipelines that both feed the same cache DB.
- Shared limits/constants live in each pipeline's own `_00_constants.py`
  — a value only moves there once it's used in 2+ files in that pipeline.
  Don't centralize everything into one giant constants file.
- The cache DB admin password (`CACHE_DB_ADMIN_PASSWORD`) is a
  deliberate, acknowledged **soft** protection, not real multi-user auth.
  Don't "fix" this by building real auth unless asked — it's a known,
  intentional simplification for now.
- Supported attachment types are deliberately narrow: PDF and Word are
  the two main ones, then Excel, then text/CSV. HTML and Markdown are
  explicitly NOT supported — don't add them back in.
- Every file scanner/extractor exception is fail-closed by design
  (reject on any doubt). Don't loosen this to "fix" a rejection unless
  the rejection is actually wrong.

## Local environment

- M1 MacBook Pro, 16GB RAM. Money's tight — prefer free/local tooling
  over paid APIs wherever there's a choice.
- Postgres: EnterpriseDB Postgres 17 (`/Library/PostgreSQL/17`) — do NOT
  install `postgresql@16` via brew alongside it.
- ClamAV (`brew install clamav`) must have `freshclam` running on its own
  schedule outside this app — a clean scan against a stale signature DB
  is a false sense of security, and the scanner code can't fix that.
- Model weights (`vision_models/`, `text_models/`) are gitignored and
  fetched via `python download_model.py` from `requirements.models.txt`
  — don't assume they're present without checking.

## Ground rule

This file is context, not a task list. Don't start building or "fixing"
things just because you read this — wait for the actual instruction
(e.g. `TESTING_PLAN.md`, or whatever Amrit asks for directly).
