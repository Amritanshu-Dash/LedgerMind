import os
import time
import mimetypes
import logging
import requests
from pathlib import Path
from urllib.parse import urlparse, unquote
from email.message import Message
from uuid import uuid4
from datetime import datetime, timedelta

# Module-level logger – configuration is left to the application.
logger = logging.getLogger(__name__)

# ==============================
# Configuration
# ==============================

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls",
    ".csv", ".txt", ".png", ".jpg", ".jpeg"
}

MAX_FILE_SIZE_MB = 500
DOWNLOAD_TIMEOUT = 120  # seconds
TEMP_DOWNLOAD_DIR = Path(__file__).resolve().parent / "temp_downloads"
MAX_TEMP_FILE_AGE_HOURS = 24  # Auto-delete temp files older than this


# ==============================
# Helper Functions
# ==============================

def is_url(path: str) -> bool:
    """Check if the given string is a valid URL."""
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


def download_from_url(url: str) -> str:
    """
    Download file from a public URL and save it locally.
    Returns the local file path.
    """
    logger.info(f"Starting download from URL: {url}")
    TEMP_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_old_temp_files()

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; LedgerMind/1.0; +https://github.com/)"
    }

    try:
        response = requests.get(
            url,
            stream=True,
            timeout=DOWNLOAD_TIMEOUT,
            headers=headers
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        logger.error(f"Connection timed out for URL: {url}")
        raise TimeoutError("Download timed out while connecting. Please try again.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Download request failed for URL {url}: {e}")
        raise ConnectionError(f"Failed to download file: {str(e)}")

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
        raw_name = unquote(Path(urlparse(url).path).name)
        if raw_name and "." in raw_name:
            filename = raw_name

    if not filename or "." not in filename:
        content_type = response.headers.get("content-type", "")
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".bin"
        filename = f"downloaded_file{ext}"
        logger.debug(f"Using fallback filename based on content-type: {filename}")

    # Prevent path traversal
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