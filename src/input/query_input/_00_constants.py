"""
_00_constants.py
----------------
Shared numbers and word lists for the query pipeline.
Anything used in more than one query file should live here so we don't copy the same limit or keyword list into three scripts and then forget to update one of them.
"""

# ----- Size limits -----
# Shortest query we will even try to understand.
# "A" or "?" alone is not enough to be a real question.
MIN_QUERY_CHARS = 2

# Longest query we accept.
# Stops someone pasting a whole book into the box and hanging the pipeline.
MAX_QUERY_CHARS = 2000

# Hard cap on files attached to one query.
# Protects the orchestrator from a huge list of paths in one call.
MAX_ATTACHMENTS = 20


# ----- Intent names -----
# These strings are the only "senses" analysis is allowed to return.
# The predictor and the DB should use these same names, not free text.

# User wants a recap of an attached document.
INTENT_SUMMARIZE_DOCUMENT = "summarize_document"

# User wants takeaways / analysis of an attached document.
INTENT_INSIGHTS_ON_DOCUMENT = "insights_on_document"

# User is asking about a company / ticker, with or without a file.
INTENT_COMPANY_INSIGHT = "company_insight"

# Finance-related, but not clearly "this file" or "this ticker".
INTENT_OTHER_FINANCE = "other_finance"

# Not finance and not about an attached file — we should not call the model.
INTENT_OUT_OF_SCOPE = "out_of_scope"

# Could be valid, but we don't have enough (e.g. "summarize this" and no file).
INTENT_UNCLEAR = "unclear"

# Fast membership check: "is this a known intent?"
VALID_INTENTS = {
    INTENT_SUMMARIZE_DOCUMENT,
    INTENT_INSIGHTS_ON_DOCUMENT,
    INTENT_COMPANY_INSIGHT,
    INTENT_OTHER_FINANCE,
    INTENT_OUT_OF_SCOPE,
    INTENT_UNCLEAR,
}


# ----- Keyword lists for v1 rules -----
# Not a trained model. Just cheap clues so we can route a query.
# Lowercased matching happens in analysis; keep these in lowercase.

# Looks like they want a short recap.
SUMMARIZE_KEYWORDS = ("summarize", "summary", "sum up", "tl;dr", "tl dr")

# Looks like they want analysis, not just a recap.
INSIGHT_KEYWORDS = ("insight", "insights", "analyse", "analyze", "analysis")

# Looks like markets / company / filings — treat as in-scope finance.
FINANCE_KEYWORDS = (
    "stock",
    "stocks",
    "share",
    "shares",
    "ticker",
    "portfolio",
    "invest",
    "investment",
    "revenue",
    "profit",
    "loss",
    "earnings",
    "dividend",
    "market",
    "finance",
    "financial",
    "filing",
    "10-k",
    "10-q",
    "exhibit",
    "sec",
    "mutual fund",
    "etf",
)

# Looks like they are talking about an uploaded file, not a company in general.
DOCUMENT_KEYWORDS = (
    "file",
    "pdf",
    "document",
    "attachment",
    "exhibit",
    "this file",
    "this document",
)