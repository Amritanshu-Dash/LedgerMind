import logging
import subprocess
from pathlib import Path
from typing import Dict, Optional
from shutil import which

logger = logging.getLogger(__name__)

# ==============================
# Custom Exceptions
# ==============================

class MalwareDetectedError(Exception):
    """Raised when a file is found to be infected."""
    pass


class ScannerNotAvailableError(Exception):
    """Raised when ClamAV is not installed or not working."""
    pass


# Module-level cache for ClamAV availability
_clamav_available: Optional[bool] = None


def is_clamav_available() -> bool:
    """Check if ClamAV (clamscan) is installed and accessible (cached)."""
    global _clamav_available

    if _clamav_available is None:
        if which("clamscan") is None:
            _clamav_available = False
        else:
            try:
                result = subprocess.run(
                    ["clamscan", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                _clamav_available = result.returncode == 0
            except (subprocess.TimeoutExpired, Exception):
                # Log the reason at DEBUG level for troubleshooting
                logger.debug("ClamAV availability check failed", exc_info=True)
                _clamav_available = False

    return _clamav_available


def scan_file(
    file_path: str,
    timeout: int = 120,
    max_size_mb: Optional[float] = None
) -> Dict[str, str]:
    """
    Scan a file for malware using ClamAV.

    Args:
        file_path: Absolute path of the file.
        timeout: Maximum seconds for the scan.
        max_size_mb: If set, raise ValueError if the file exceeds this size.

    Returns:
        dict with "status", "message", "file" on clean scan.

    Raises:
        MalwareDetectedError: If the file is infected.
        ScannerNotAvailableError: If ClamAV is not available.
        FileNotFoundError, ValueError, RuntimeError
    """
    path = Path(file_path).resolve()

    if not path.exists():
        logger.error(f"File not found for scanning: {path}")
        raise FileNotFoundError(f"File does not exist: {path}")

    if not path.is_file():
        logger.error(f"Path is not a file: {path}")
        raise ValueError(f"Path is not a file: {path}")

    # Optional size check
    if max_size_mb is not None:
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > max_size_mb:
            raise ValueError(
                f"File too large to scan ({size_mb:.2f} MB). Max: {max_size_mb} MB"
            )

    if not is_clamav_available():
        raise ScannerNotAvailableError(
            "ClamAV is not installed or not available. "
            "Install ClamAV to enable malware scanning."
        )

    logger.info(f"Starting malware scan for: {path}")

    try:
        result = subprocess.run(
            ["clamscan", "--no-summary", "--infected", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout
        )
    except subprocess.TimeoutExpired:
        logger.error(f"ClamAV scan timed out for: {path}")
        raise RuntimeError("Malware scan timed out.")
    except Exception as e:
        logger.error(f"Unexpected error running ClamAV: {e}")
        raise RuntimeError(f"Failed to run malware scan: {str(e)}")

    if result.returncode == 0:
        logger.info(f"File is safe: {path}")
        return {
            "status": "safe",
            "message": "No malware detected.",
            "file": str(path)
        }

    elif result.returncode == 1:
        output = result.stdout.strip() or result.stderr.strip()
        logger.warning(f"Malware detected in {path}: {output}")
        raise MalwareDetectedError(
            f"Malware detected in {path.name}. Scan output: {output}"
        )

    else:
        error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown scanner error"
        logger.error(f"ClamAV error for {path}: {error_msg}")
        raise RuntimeError(f"Malware scan failed: {error_msg}")