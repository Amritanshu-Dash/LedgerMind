"""
input.py
--------
Input acquisition stage — the FIRST step of the pipeline, before the scanner ever sees a file. Accepts either a local file path or a public URL and turns either one into a validated local file path.

Purpose:
This file's job is narrow and deliberately dumb: "get me a real, readable, reasonably-sized, plausibly-supported file onto local disk." It does NOT scan for malware (scanner.py) and does NOT decide if content is
extractable (extractor.py) — those are separate concerns, separate files.

Why the URL path needs its own guardian logic (SSRF):
Unlike a local file path (which the person running this app already has access to), a URL means THIS APPLICATION makes an outbound network request on the caller's behalf. Without care, that turns this app into a
proxy an attacker can use to reach things it shouldn't — internal services, cloud metadata endpoints (a common source of leaked credentials), or anything else on a private network. So every URL is
validated against private/loopback/link-local address ranges BEFORE any connection is made, and every redirect hop is re-validated the same way, since a URL that looks safe can still redirect somewhere unsafe.

Honest limitation: 
this defends against the common case (an attacker supplying an obviously-internal URL or a malicious redirect), but does not fully close DNS-rebinding attacks, where a hostname's IP changes
between our validation check and the actual connection. Fully closing that would mean pinning the connection to the exact IP we validated (bypassing a second DNS lookup at request time), which adds real
complexity — not implemented here, flagged as a known gap rather than silently claimed as solved.

Shared constants:
File size and extension limits are imported directly from scanner.py rather than redefined here, so the two stages can never quietly drift out of sync (e.g. this file allowing a 500MB download that the scanner
was only ever going to reject at 50MB).

"""

import ipaddress                       # checks resolved IPs against private/loopback/reserved ranges
import logging                         # structured logging instead of print()
import mimetypes                       # guesses a file extension from Content-Type as a last resort
import os                              # used for file permission checks (os.access)
import socket                          # resolves hostnames to IPs for the SSRF check
import time                            # tracks elapsed download time against the timeout
from datetime import datetime, timedelta   # temp-file age tracking for cleanup
from email.message import Message      # parses Content-Disposition header safely
from pathlib import Path               # safe, OS-independent path handling
from urllib.parse import urljoin, urlparse, unquote  # URL parsing/resolution
from uuid import uuid4                 # unique temp filenames, avoids collisions

import requests                        # HTTP client for downloading remote files

from .scanner import ALLOWED_EXTENSIONS as SUPPORTED_EXTENSIONS  # single source of truth, see module docstring
from .scanner import DEFAULT_MAX_SIZE_MB as MAX_FILE_SIZE_MB     # same — kept in sync with the scanner's own cap

logger = logging.getLogger(__name__)   # module-level logger tagged with this file's name


# ==============================
# Configuration
# ==============================
# Note: MAX_FILE_SIZE_MB and SUPPORTED_EXTENSIONS are imported from
# scanner.py above, not defined here — see the module docstring for why.

DOWNLOAD_TIMEOUT = 120          # seconds, bounds TOTAL download wall-clock time (see the manual check below)
TEMP_DOWNLOAD_DIR = Path(__file__).resolve().parent / "temp_downloads"
MAX_TEMP_FILE_AGE_HOURS = 24     # auto-delete temp files older than this
MAX_REDIRECTS = 5                # redirect hops we'll follow, each one re-validated for SSRF


class SuspiciousURLError(Exception):
    """Raised when a URL resolves to a private/internal/reserved address,
    or a redirect tries to send us to one. Callers must treat this as
    fail-closed — never fetch the URL anyway."""
    pass


# ==============================
# Helper Functions
# ==============================

def is_url(path: str) -> bool:
    """Check if the given string is a valid http/https URL."""
    try:
        result = urlparse(path)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False


def get_file_extension(path: str) -> str:
    """Extract file extension in lowercase."""
    return Path(path).suffix.lower()


def is_supported_file(path: str) -> bool:
    """Check if file type is supported by extension."""
    return get_file_extension(path) in SUPPORTED_EXTENSIONS


def cleanup_old_temp_files():
    """Delete temporary files older than MAX_TEMP_FILE_AGE_HOURS."""
    if not TEMP_DOWNLOAD_DIR.exists():
        logger.debug("Temp directory does not exist, skipping cleanup.")
        return

    cutoff = datetime.now() - timedelta(hours=MAX_TEMP_FILE_AGE_HOURS)
    deleted_count = 0

    for file in TEMP_DOWNLOAD_DIR.iterdir():
        if file.is_file():
            file_mtime = datetime.fromtimestamp(file.stat().st_mtime)
            if file_mtime < cutoff:
                try:
                    file.unlink()
                    deleted_count += 1
                    logger.debug(f"Deleted old temp file: {file.name}")
                except Exception as e:
                    logger.warning(f"Could not delete temp file {file.name}: {e}")

    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} old temporary file(s).")


def validate_local_file(file_path: str) -> str:
    """
    Validate a local file.
    Returns absolute path if valid, else raises an appropriate exception.
    """
    logger.debug(f"Validating local file: {file_path}")
    path = Path(file_path).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(f"File does not exist: {path}")

    if not path.is_file():
        raise ValueError(f"Path is not a file: {path}")

    if not os.access(path, os.R_OK):
        raise PermissionError(f"No read permission for file: {path}")

    file_size_mb = path.stat().st_size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(
            f"File too large ({file_size_mb:.2f} MB). Max allowed is {MAX_FILE_SIZE_MB} MB"
        )

    if not is_supported_file(str(path)):
        raise ValueError(f"Unsupported file type: {path.suffix}")

    logger.info(f"Local file validated successfully: {path}")
    return str(path)


# ==============================
# SSRF protection
# ==============================

def _assert_url_is_safe(url: str) -> None:
    """
    Resolves the URL's hostname and rejects it if any resolved address is
    private, loopback, link-local, reserved, or otherwise not a normal
    public internet address. Raises SuspiciousURLError if unsafe.

    Called once for the original URL, and again for every redirect hop —
    a URL that looks safe can still redirect somewhere that isn't.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SuspiciousURLError(f"Unsupported URL scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise SuspiciousURLError("URL has no hostname.")

    try:
        # getaddrinfo returns every address (IPv4 and IPv6) this hostname
        # resolves to — we reject the URL if ANY of them is unsafe, not
        # just the first one.
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise SuspiciousURLError(f"Could not resolve hostname '{hostname}': {e}")

    for family, _, _, _, sockaddr in resolved:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise SuspiciousURLError(f"Resolved address is not a valid IP: {ip_str}")

        if (
            ip.is_private        # RFC1918 ranges (10.x, 172.16-31.x, 192.168.x) and IPv6 equivalents
            or ip.is_loopback     # 127.0.0.1, ::1
            or ip.is_link_local   # 169.254.0.0/16 — this covers cloud metadata endpoints too
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified  # 0.0.0.0
        ):
            raise SuspiciousURLError(
                f"URL hostname '{hostname}' resolves to a private/internal address ({ip_str}). "
                f"Refusing to fetch it."
            )


# ==============================
# Download
# ==============================

def download_from_url(url: str) -> str:
    """
    Download file from a public URL and save it locally.
    Returns the local file path.
    """
    logger.info(f"Starting download from URL: {url}")
    _assert_url_is_safe(url)  # first check, before any connection is made

    TEMP_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_old_temp_files()

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; LedgerMind/1.0; +https://github.com/)"
    }

    # We manually follow redirects (allow_redirects=False) instead of
    # letting requests do it automatically, so every hop can be
    # re-validated against the SSRF check above before we follow it.
    current_url = url
    response = None
    try:
        for hop in range(MAX_REDIRECTS + 1):
            resp = requests.get(
                current_url,
                stream=True,
                timeout=DOWNLOAD_TIMEOUT,
                headers=headers,
                allow_redirects=False,
            )
            if resp.is_redirect or resp.is_permanent_redirect:
                next_url = urljoin(current_url, resp.headers.get("location", ""))
                resp.close()  # release this hop's connection before following the next one
                if hop == MAX_REDIRECTS:
                    raise ConnectionError(f"Too many redirects (limit {MAX_REDIRECTS}).")
                _assert_url_is_safe(next_url)  # re-validate EVERY hop, not just the first URL
                current_url = next_url
                continue
            resp.raise_for_status()
            response = resp
            break
    except requests.exceptions.Timeout:
        logger.error(f"Connection timed out for URL: {url}")
        raise TimeoutError("Download timed out while connecting. Please try again.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Download request failed for URL {url}: {e}")
        raise ConnectionError(f"Failed to download file: {str(e)}")

    if response is None:
        raise ConnectionError("Failed to obtain a response after following redirects.")

    with response:  # guarantees the underlying connection is released even if writing fails below
        # -----------------------------------------------------------------
        # Safely determine the filename
        # -----------------------------------------------------------------
        content_disposition = response.headers.get("content-disposition", "")
        filename = None

        if content_disposition:
            msg = Message()
            msg["content-disposition"] = content_disposition
            filename = msg.get_filename()

        if not filename:
            raw_name = unquote(Path(urlparse(current_url).path).name)
            if raw_name and "." in raw_name:
                filename = raw_name

        if not filename or "." not in filename:
            content_type = response.headers.get("content-type", "")
            ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".bin"
            filename = f"downloaded_file{ext}"
            logger.debug(f"Using fallback filename based on content-type: {filename}")

        # Prevent path traversal — only ever keep the filename component.
        filename = Path(filename).name
        if not filename:
            filename = "downloaded_file.bin"
            logger.debug("Empty filename after sanitization, using fallback.")

        # Unique name to avoid collisions
        unique_filename = f"{uuid4().hex}_{filename}"
        local_path = TEMP_DOWNLOAD_DIR / unique_filename
        logger.debug(f"Saving file as: {unique_filename}")

        # -----------------------------------------------------------------
        # Download with size + timeout protection
        # -----------------------------------------------------------------
        total_size = 0
        max_size_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
        start_time = time.time()

        try:
            with open(local_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if time.time() - start_time > DOWNLOAD_TIMEOUT:
                        raise TimeoutError("Download timed out while reading data.")

                    if chunk:
                        total_size += len(chunk)
                        if total_size > max_size_bytes:
                            raise ValueError(
                                f"File too large. Max allowed is {MAX_FILE_SIZE_MB} MB"
                            )
                        f.write(chunk)
        except Exception as e:
            # Clean up partial file
            if local_path.exists():
                local_path.unlink(missing_ok=True)
                logger.debug(f"Removed partial download: {local_path}")
            logger.error(f"Download failed: {e}")
            raise e

    if not is_supported_file(str(local_path)):
        local_path.unlink(missing_ok=True)
        logger.error(f"Unsupported file type downloaded: {local_path.suffix}")
        raise ValueError(f"Downloaded file type not supported: {local_path.suffix}")

    logger.info(f"Download completed successfully: {local_path}")
    return str(local_path.resolve())


# ==============================
# Main Function
# ==============================

def get_file(input_source: str) -> str:
    """
    Main entry point.

    Accepts either:
    - Local file path
    - Public URL

    Returns:
        str: Absolute path to a valid local file
    """
    if not input_source or not isinstance(input_source, str):
        logger.error("get_file called with empty or invalid input.")
        raise ValueError("Input source cannot be empty")

    input_source = input_source.strip()

    if not input_source:
        logger.error("get_file called with whitespace-only input.")
        raise ValueError("Input source cannot be empty")

    if is_url(input_source):
        return download_from_url(input_source)

    logger.debug(f"Treating input as local file: {input_source}")
    return validate_local_file(input_source)


# ==============================
# Quick Test
# ==============================

if __name__ == "__main__":
    # Configure basic logging for stand-alone testing
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    try:
        # path = get_file("https://example.com/sample.pdf")
        path = get_file("/Users/amritanshudash/Downloads/FY26_Q1_Consolidated_Financial_Statements.pdf")
        print("✅ File ready at:", path)
    except Exception as e:
        print("❌ Error:", str(e))