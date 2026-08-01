"""
constants.py
------------
Shared constants for the input-processing pipeline.

Rule for what belongs in this file, and nothing else: a value only goes here if it's actually used in 2 or more files. A constant used in just one file stays defined right next to the code that uses it — moving everything into one giant file 
"for consistency" makes it harder to see what a given file actually depends on, not easier.

Naming rule: every name here should be unambiguous on its own, with no chance of confusing it with something similarly-named elsewhere. For example, vision_model.py has its OWN local MAX_FILE_SIZE_MB (15MB, images only) and its OWN 
local ALLOWED_EXTENSIONS (image types only) — those are deliberately NOT here, because they only matter inside that one file, and if they were named the same as the pipeline-wide versions below, someone reading logs or code later could easily 
mix up a 15MB image-only limit with a 50MB whole-pipeline limit. Precise, non-generic names are the actual fix for that, not just centralizing everything.
"""

from pathlib import Path  # safe, OS-independent path handling
from types import MappingProxyType  # a genuinely read-only view of a dict — see note below
from typing import Final  # marks a name as "should never be reassigned" for static type checkers

# A note on "constant" in Python, since it's not a real language feature
# like it is in C++:
# Python has no compiler-enforced const. `Final` (below) tells a type
# checker (mypy, or your IDE's built-in checker) to flag any attempt to
# REASSIGN one of these names — but that check only runs if you actually
# run a type checker; the Python interpreter itself won't stop it.
# For the dict/set values specifically, there's a second, sharper gap:
# even a name that's never reassigned can still have its CONTENTS mutated
# in place (e.g. SUPPORTED_FILE_MAGIC_BYTES[".exe"] = [...]). MappingProxyType
# and frozenset close that gap for real, at runtime, with no type checker
# needed — they raise TypeError the instant anyone tries to mutate them.


# ============================================================
# File size limit — used by scanner.py, input.py, orchestrator.py
# ============================================================
# The single cap applied to any file entering the pipeline, whether it
# arrived as a local upload or was downloaded from a URL. Change it here
# and every stage picks up the new value automatically.
DEFAULT_MAX_UPLOAD_FILE_SIZE_MB: Final[float] = 50.0


# ============================================================
# Supported file types — used by scanner.py (magic-byte validation) and
# input.py (early extension check before a download/local file even
# reaches the scanner)
# ============================================================
# This is the single authoritative list of what the whole pipeline
# accepts. Each extension maps to the real byte signature(s) its file
# format starts with — scanner.py uses this to catch a file lying about
# its own type (e.g. a renamed file). input.py only needs the extension
# set (the dict's keys), not the byte signatures themselves, for its own
# quick early check.
#
# Wrapped in MappingProxyType / built as a frozenset so these are
# genuinely immutable at runtime, not just named in ALL_CAPS by
# convention — see the note above.
SUPPORTED_FILE_MAGIC_BYTES: Final[MappingProxyType] = MappingProxyType({
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".bmp": (b"BM",),
    ".webp": (b"RIFF",),  # full check also verifies "WEBP" at offset 8, see scanner.py
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    ".pptx": (b"PK\x03\x04",),
    ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".ppt": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".txt": (b"",),
    ".csv": (b"",),
    ".json": (b"{", b"["),
    ".xml": (b"<?xml",),
    "html": (b"<!DOCTYPE html", b"<html"),
    "htm": (b"<!DOCTYPE html", b"<html"),
    "md": (b"#",),
})
SUPPORTED_FILE_EXTENSIONS: Final[frozenset] = frozenset(SUPPORTED_FILE_MAGIC_BYTES.keys())


# ============================================================
# Temp download directory — used by input.py (writes files here) and
# orchestrator.py (needs to know this path to decide whether a file is
# safe to delete/move, vs. a local file the user pointed to directly)
# ============================================================
TEMP_DOWNLOAD_DIRECTORY_PATH: Final[Path] = Path(__file__).resolve().parent / "temp_downloads"


# ==============================
# Quick Test
# ==============================
if __name__ == "__main__":
    print("=" * 60)
    print("Testing constants.py...")
    print("=" * 60)
    print(f"DEFAULT_MAX_UPLOAD_FILE_SIZE_MB : {DEFAULT_MAX_UPLOAD_FILE_SIZE_MB}")
    print(f"SUPPORTED_FILE_EXTENSIONS       : {sorted(SUPPORTED_FILE_EXTENSIONS)}")
    print(f"SUPPORTED_FILE_MAGIC_BYTES keys : {sorted(SUPPORTED_FILE_MAGIC_BYTES.keys())}")
    print(f"TEMP_DOWNLOAD_DIRECTORY_PATH    : {TEMP_DOWNLOAD_DIRECTORY_PATH}")

    # Confirm the container constants are genuinely immutable at runtime,
    # not just conventionally named — see the note at the top of this file.
    try:
        SUPPORTED_FILE_MAGIC_BYTES[".exe"] = (b"MZ",)
        print("❌ FAILED: SUPPORTED_FILE_MAGIC_BYTES was mutated, should be impossible")
    except TypeError:
        print("✅ SUPPORTED_FILE_MAGIC_BYTES is genuinely immutable at runtime")

    try:
        SUPPORTED_FILE_EXTENSIONS.add(".exe")
        print("❌ FAILED: SUPPORTED_FILE_EXTENSIONS was mutated, should be impossible")
    except AttributeError:
        print("✅ SUPPORTED_FILE_EXTENSIONS is genuinely immutable at runtime (frozenset)")