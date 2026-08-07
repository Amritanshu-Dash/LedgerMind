"""
scanner.py
----------
Malware / malicious-file guardian — the FIRST line of defense in LedgerMind.

Purpose:
Every uploaded file passes through here before the extractor or vision model ever touches it. Nothing downstream should trust a file that hasn't come back "safe" from this module.

Why this isn't just "run ClamAV and call it a day":
A signature scanner (ClamAV or any other) can only catch malware that's already known and in its database. That leaves real gaps:
  - Brand-new / custom-crafted malicious files (no signature exists yet).
  - "Zip bombs" — a tiny DOCX/XLSX (which are just ZIP files under the
    hood) that decompresses into gigabytes and hangs or crashes whatever
    tries to unzip it downstream. This isn't "malware" a signature
    database would flag, but it can take your app down just as hard.
  - Office documents with embedded macros — not always flagged by
    signatures, and we never need macros to read financial data anyway.
  - PDFs with embedded JavaScript / launch actions — same story.
  - A file whose extension lies about what it actually is.
So this module runs several independent layers, in order from cheapest to most expensive, and rejects at the first layer that fails. ClamAV is one layer among several, not the whole defense.

Operational note:
ClamAV's own signature database (layer below) is only useful if freshclam runs on its own schedule outside this app. A clean scan against a stale database is a false sense of security — this module cannot fix that, only remind you of it.

Fail-open vs fail-closed:
Every exception this module raises means "reject the file." Callers must never catch one of these and let the file through anyway — that would defeat the entire point of having a guardian stage.
"""

import logging               # structured logging instead of print()
import os                    # used for POSIX-only resource limiting (see _run_signature_scan)
import re                    # used to search raw PDF bytes for active-content markers
import subprocess            # runs clamscan as a real subprocess, no shell involved
import zipfile                # DOCX/XLSX/PPTX are ZIP files — used for the zip-bomb check
from dataclasses import dataclass  # lightweight structured result object
from pathlib import Path      # safe, OS-independent path handling
from shutil import which      # cheap check for whether clamscan is even on PATH
from typing import Optional   # type hints so signatures are self-documenting

from ._00_constants import DEFAULT_MAX_UPLOAD_FILE_SIZE_MB, SUPPORTED_FILE_MAGIC_BYTES

logger = logging.getLogger(__name__)  # module-level logger tagged with this file's name


# ==============================
# CONFIGURATION
# ==============================
# Every "how strict" knob lives here so tuning doesn't require touching logic.
# Note: file size limit and supported file types now live in constants.py,
# since both are shared with input.py / orchestrator.py — see that file
# for why they moved out of here.

DEFAULT_SCAN_TIMEOUT_SECONDS = 120     # ClamAV scan itself
VERSION_CHECK_TIMEOUT_SECONDS = 10     # the lightweight "is clamscan alive" check

# Resource limits applied to the clamscan subprocess itself (POSIX only) —
# defense in depth in case a crafted file somehow makes the scanner itself
# misbehave (hang or balloon in memory).
CLAMSCAN_CPU_LIMIT_SECONDS = 60
CLAMSCAN_MEMORY_LIMIT_MB = 1024

# Zip-bomb thresholds (applies to DOCX/XLSX/PPTX, which are ZIP archives).
MAX_ZIP_ENTRY_COUNT = 2000             # a normal Office file has dozens, not thousands
MAX_ZIP_UNCOMPRESSED_TOTAL_MB = 500    # total size after decompression
MAX_ZIP_COMPRESSION_RATIO = 100        # uncompressed / compressed — bombs are 1000x+


# These formats get the zip-bomb + macro check (see _check_zip_safety).
# Local to this file only — nothing else needs to know which extensions
# happen to be ZIP-based under the hood.
ZIP_BASED_EXTENSIONS = {".docx", ".xlsx", ".pptx"}


# ==============================
# Custom Exceptions
# ==============================
# Every one of these means the same thing to a caller: reject the file.

class MalwareDetectedError(Exception):
    """
    Raised when a signature scan (ClamAV) flags the file as infected.
    """
    pass


class SuspiciousFileError(Exception):
    """
    Raised when a file fails a structural check — zip bomb, embedded macro, active PDF content, or a mismatched file type. No virus signature is needed to catch these; the file's own structure is the evidence.
    """
    pass


class ScannerNotAvailableError(Exception):
    """
    Raised when ClamAV is not installed or not working. Callers must treat this as fail-closed — do NOT let the file through just because the signature scanner itself is unavailable.
    """
    pass


@dataclass
class ScanResult:
    """
    Outcome of a full scan_file() call.
    """
    status: str          # always "safe" — anything else raises instead of returning
    file: str            # the resolved path that was scanned
    checks_passed: list  # names of every layer this file passed, for logging/audit


# ==============================
# LAYER 1 — File type honesty check
# ==============================
# Confirms the file's actual bytes match what its extension claims. Catches
# the simplest and most common trick: renaming a malicious file to look
# like a harmless one.

def _verify_magic_bytes(path: Path) -> None:
    """
    Raises SuspiciousFileError if the file's real content doesn't match its extension. Silent pass (returns None) if it matches.
    """
    ext = path.suffix.lower()
    if ext not in SUPPORTED_FILE_MAGIC_BYTES:
        raise SuspiciousFileError(f"Unsupported file type: '{ext}'.")

    try:
        with open(path, "rb") as f:
            header = f.read(16)  # more than enough for every signature we check
    except Exception as e:
        raise SuspiciousFileError(f"Could not read file header: {e}")

    if not any(header.startswith(sig) for sig in SUPPORTED_FILE_MAGIC_BYTES[ext]):
        raise SuspiciousFileError(
            f"File content does not match its extension '{ext}' "
            f"(claims to be one type, is actually something else)."
        )

    # WEBP needs a second check: "RIFF" alone is shared by other formats
    # (WAV, AVI); the real marker is "WEBP" starting at byte offset 8.
    if ext == ".webp" and header[8:12] != b"WEBP":
        raise SuspiciousFileError("File claims to be WEBP but is a different RIFF format.")


# ==============================
# LAYER 2 — Zip-bomb + macro check (DOCX/XLSX/PPTX only)
# ==============================
# These formats are ZIP archives. A malicious one can be tiny on disk but
# expand into gigabytes when unzipped downstream, or carry an embedded
# macro we never need for reading financial data out of a document.

def _check_zip_safety(path: Path) -> None:
    """
    Raises SuspiciousFileError on a zip bomb or an embedded macro. Only call this for files in ZIP_BASED_EXTENSIONS.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            entries = zf.infolist()

            if len(entries) > MAX_ZIP_ENTRY_COUNT:
                raise SuspiciousFileError(
                    f"Archive has {len(entries)} entries, "
                    f"limit is {MAX_ZIP_ENTRY_COUNT} (possible zip bomb)."
                )

            total_uncompressed = 0
            for entry in entries:
                total_uncompressed += entry.file_size

                # Per-entry compression ratio check — a single wildly
                # over-compressed entry is the classic zip-bomb signature,
                # even if the archive-wide total still looks small.
                if entry.compress_size > 0:
                    ratio = entry.file_size / entry.compress_size
                    if ratio > MAX_ZIP_COMPRESSION_RATIO:
                        raise SuspiciousFileError(
                            f"Entry '{entry.filename}' has a {ratio:.0f}x "
                            f"compression ratio (possible zip bomb)."
                        )

                # Macro-enabled Office files store their VBA code in this
                # specific entry name — we never need macros for reading
                # financial data, so any macro is grounds for rejection.
                if entry.filename.lower().endswith("vbaproject.bin"):
                    raise SuspiciousFileError(
                        "File contains an embedded macro (vbaProject.bin), "
                        "which this pipeline does not accept."
                    )

            total_uncompressed_mb = total_uncompressed / (1024 * 1024)
            if total_uncompressed_mb > MAX_ZIP_UNCOMPRESSED_TOTAL_MB:
                raise SuspiciousFileError(
                    f"Archive would decompress to {total_uncompressed_mb:.0f}MB, "
                    f"limit is {MAX_ZIP_UNCOMPRESSED_TOTAL_MB}MB (possible zip bomb)."
                )

    except zipfile.BadZipFile:
        raise SuspiciousFileError("File claims to be an Office document but is not a valid ZIP archive.")
    except SuspiciousFileError:
        raise  # re-raise our own checks above without wrapping them again
    except Exception as e:
        # Any other zipfile-level failure — treat as unsafe rather than
        # letting it propagate as a raw, confusing exception.
        raise SuspiciousFileError(f"Could not safely inspect archive contents: {e}")


# ==============================
# LAYER 3 — Active-content check (PDF only)
# ==============================
# We only need PDFs for reading text/numbers/tables out of them. Any PDF
# carrying JavaScript, launch actions, or auto-run actions has no
# legitimate reason to be in this pipeline.

_PDF_DANGEROUS_MARKERS = [
    rb"/JavaScript",
    rb"/JS\b",
    rb"/OpenAction",
    rb"/Launch",
    rb"/EmbeddedFile",
]


def _check_pdf_safety(path: Path) -> None:
    """
    Raises SuspiciousFileError if the PDF contains active-content markers.
    """
    try:
        with open(path, "rb") as f:
            content = f.read()  # PDFs in this pipeline are capped by MAX_SIZE anyway
    except Exception as e:
        raise SuspiciousFileError(f"Could not read PDF for inspection: {e}")

    for pattern in _PDF_DANGEROUS_MARKERS:
        if re.search(pattern, content):
            raise SuspiciousFileError(
                f"PDF contains active-content marker '{pattern.decode(errors='ignore')}', "
                f"which this pipeline does not accept."
            )


# ==============================
# LAYER 4 — ClamAV signature scan
# ==============================
# The classic "does this match a known virus" check. Kept as one layer
# among several, not the whole defense — see the module docstring for why.

_clamav_confirmed_working: bool = False  # only ever caches a POSITIVE result, see below


def is_clamav_available() -> bool:
    """
    Check if ClamAV (clamscan) is installed and responding.

    Caching policy: once confirmed working, we trust that for the rest of the process. We never cache a FAILURE — a one-time slow start or transient hiccup should not permanently disable scanning for every file for the rest of the process's life.
    """
    global _clamav_confirmed_working

    if _clamav_confirmed_working:
        return True

    if which("clamscan") is None:  # fast PATH lookup, no subprocess spawned
        return False

    try:
        result = subprocess.run(
            ["clamscan", "--version"],
            capture_output=True,
            text=True,
            timeout=VERSION_CHECK_TIMEOUT_SECONDS,
        )
        _clamav_confirmed_working = result.returncode == 0
        return _clamav_confirmed_working
    except subprocess.TimeoutExpired:
        logger.debug("ClamAV version check timed out.")
        return False
    except Exception:
        logger.debug("ClamAV availability check failed", exc_info=True)
        return False


def _apply_subprocess_resource_limits() -> None:
    """
    Runs INSIDE the child process (via subprocess's preexec_fn) right after fork, before clamscan's own code starts executing. Caps CPU time and memory so that even a file crafted to make the scanner itself misbehave can't hang or balloon the machine. POSIX only (macOS/Linux) — Windows
    would need a different mechanism (e.g. a Job Object) not implemented here.
    """
    import resource  # POSIX-only stdlib module; imported here so this file
                      # still imports cleanly on a platform without it

    try:
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (CLAMSCAN_CPU_LIMIT_SECONDS, CLAMSCAN_CPU_LIMIT_SECONDS),
        )

    except (ValueError, OSError):
        pass # not fatal — the scan's own timeout still bounds wall-clock time

    try:
        resource.setrlimit(
            resource.RLIMIT_AS,
            (CLAMSCAN_MEMORY_LIMIT_MB * 1024 * 1024, CLAMSCAN_MEMORY_LIMIT_MB * 1024 * 1024),
        )
    except (ValueError, OSError):
        pass  # RLIMIT_AS is unreliable when set from a forked Python
              # process on macOS — see the earlier explanation. Best-effort.


def _run_signature_scan(path: Path, timeout: int) -> None:
    """
    Raises MalwareDetectedError, ScannerNotAvailableError, or RuntimeError. Returns None on a clean scan.
    """
    if not is_clamav_available():
        raise ScannerNotAvailableError(
            "ClamAV is not installed or not available. "
            "Install ClamAV to enable signature-based malware scanning."
        )

    logger.info(f"Starting ClamAV signature scan for: {path}")

    # preexec_fn only works on POSIX; skip resource limiting on Windows
    # rather than crashing the whole scan over it.
    limiter = _apply_subprocess_resource_limits if os.name == "posix" else None

    try:
        result = subprocess.run(
            # List form (not shell=True) — arguments go straight to the OS,
            # so nothing in the filename can be interpreted as a shell
            # command even if it contains quotes, semicolons, etc.
            ["clamscan", "--no-summary", "--infected", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=limiter,
        )
    except subprocess.TimeoutExpired:
        logger.error(f"ClamAV scan timed out for: {path}")
        raise RuntimeError("Malware scan timed out.")
    except Exception as e:
        logger.error(f"Unexpected error running ClamAV: {e}")
        raise RuntimeError(f"Failed to run malware scan: {str(e)}")

    # clamscan exit codes: 0 = clean, 1 = virus found, anything else = error.
    if result.returncode == 0:
        logger.info(f"ClamAV: file is clean: {path}")
        return
    elif result.returncode == 1:
        output = result.stdout.strip() or result.stderr.strip()
        logger.warning(f"Malware detected in {path}: {output}")
        raise MalwareDetectedError(f"Malware detected in {path.name}. Scan output: {output}")
    else:
        error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown scanner error"
        logger.error(f"ClamAV error for {path}: {error_msg}")
        raise RuntimeError(f"Malware scan failed: {error_msg}")


# ==============================
# LAYER 0 — Path / size sanity (runs first, cheapest checks)
# ==============================

def _is_within_directory(path: Path, allowed_base_dir: Path) -> bool:
    """
    True if `path` resolves to somewhere inside `allowed_base_dir`. Guards against a symlink pointing outside the intended uploads folder — Path.resolve() follows symlinks, so without this check we could scan (and the pipeline later trust) a different file entirely
    than the one that was actually uploaded.
    """
    try:
        path.relative_to(allowed_base_dir)
        return True
    except ValueError:
        return False


# ==============================
# PUBLIC ENTRY POINT
# ==============================

def scan_file(
    file_path: str,
    timeout: int = DEFAULT_SCAN_TIMEOUT_SECONDS,
    max_size_mb: Optional[float] = DEFAULT_MAX_UPLOAD_FILE_SIZE_MB,
    allowed_base_dir: Optional[str] = None,
) -> ScanResult:
    """
    Runs a file through every defensive layer, cheapest first, and stops at the first one that fails. Only returns (a ScanResult) if every layer passes — any failure raises instead, matching the fail-closed contract described in the module docstring.

    Args:
        file_path: Absolute path of the file.
        timeout: Max seconds for the ClamAV scan step specifically.
        max_size_mb: Hard cap on file size. Defaults to DEFAULT_MAX_UPLOAD_FILE_SIZE_MB
            so there is always a cap even if the caller forgets to pass one.
        allowed_base_dir: If given, the resolved path must live inside this
            directory. Strongly recommended — pass your uploads folder.

    Raises:
        FileNotFoundError, ValueError — basic sanity failures.
        SuspiciousFileError — failed a structural check (layers 1-3).
        MalwareDetectedError — ClamAV flagged it (layer 4).
        ScannerNotAvailableError — ClamAV itself isn't usable.
        RuntimeError — the scan process itself failed unexpectedly.
    """
    checks_passed = []  # audit trail of which layers this file made it through

    path = Path(file_path).resolve()  # normalize + follow symlinks to the real target

    if not path.exists():
        raise FileNotFoundError(f"File does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Path is not a file: {path}")
    checks_passed.append("existence")

    if allowed_base_dir is not None:
        base = Path(allowed_base_dir).resolve()
        if not _is_within_directory(path, base):
            raise ValueError(f"File path is outside the allowed directory: {path}")
        checks_passed.append("path_containment")

    if max_size_mb is not None:
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > max_size_mb:
            raise ValueError(f"File too large ({size_mb:.2f}MB). Max: {max_size_mb}MB")
    checks_passed.append("size")

    # --- Layer 1: does the file's content match its claimed type? ---
    _verify_magic_bytes(path)
    checks_passed.append("magic_bytes")

    # --- Layer 2: zip-bomb / macro check, only for ZIP-based Office files ---
    if path.suffix.lower() in ZIP_BASED_EXTENSIONS:
        _check_zip_safety(path)
        checks_passed.append("zip_safety")

    # --- Layer 3: active-content check, only for PDFs ---
    if path.suffix.lower() == ".pdf":
        _check_pdf_safety(path)
        checks_passed.append("pdf_active_content")

    # --- Layer 4: known-malware signature scan ---
    _run_signature_scan(path, timeout)
    checks_passed.append("clamav_signature")

    logger.info(f"File passed all layers ({', '.join(checks_passed)}): {path}")
    return ScanResult(status="safe", file=str(path), checks_passed=checks_passed)


# ==============================
# Quick Test
# ==============================
if __name__ == "__main__":
    import tempfile

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print("=" * 60)
    print("Testing scanner.py...")
    print("=" * 60)
    print(f"ClamAV available: {is_clamav_available()}")

    # Self-contained test file — a valid PDF magic-byte header is enough to
    # pass every structural layer here, no real PDF library needed just to
    # prove the scanner's wiring works end to end.
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_path = Path(tmp_dir) / "test_sample.pdf"
        test_path.write_bytes(b"%PDF-1.4\n%%EOF")

        try:
            result = scan_file(str(test_path))
            print(f"✅ Scan passed: {result}")
        except ScannerNotAvailableError as e:
            print(f"⚠️  ClamAV not available, could not complete the scan: {e}")
        except (MalwareDetectedError, SuspiciousFileError) as e:
            print(f"❌ Unexpected rejection of a clean test file: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")