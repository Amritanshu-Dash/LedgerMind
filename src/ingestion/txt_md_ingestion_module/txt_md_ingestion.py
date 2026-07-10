"""
TXT / Markdown File Ingestion Module
====================================
Handles plain text files (.txt) and Markdown files (.md).
Clean, robust, and consistent with PDF ingestion module.
"""

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List

# ============================================================
#                        LOGGING
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
#                    VALIDATION & HELPERS
# ============================================================

def _validate_chunk_parameters(chunk_size: int, chunk_overlap: int) -> None:
    """Validate chunking parameters."""
    if not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError(f"chunk_size must be a positive integer, got {chunk_size}")
    if not isinstance(chunk_overlap, int) or chunk_overlap < 0:
        raise ValueError(f"chunk_overlap must be a non-negative integer, got {chunk_overlap}")
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be smaller than chunk_size ({chunk_size})"
        )


def _is_valid_text_file(file_path: Path) -> bool:
    """Check if the file is a supported text file (.txt or .md)."""
    return file_path.is_file() and file_path.suffix.lower() in [".txt", ".md"]


def _read_file_with_encoding(file_path: Path) -> str:
    """Try to read file with UTF-8, fallback to latin-1 if needed."""
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        logger.warning(f"UTF-8 decoding failed for {file_path.name}. Trying latin-1...")
        return file_path.read_text(encoding="latin-1")


# ============================================================
#                    TEXT CLEANING
# ============================================================

def clean_text(raw_text: str) -> str:
    """
    Clean and normalize text content.
    Removes excessive whitespace, fixes hyphenation, etc.
    """
    if not raw_text or not isinstance(raw_text, str):
        return ""

    text = raw_text

    # Fix hyphenated words broken across lines
    text = re.sub(r'-\s*\n\s*', '', text)
    text = re.sub(r'-\s+', '', text)

    # Normalize whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    # Clean lines
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    text = re.sub(r' \n', '\n', text)
    text = re.sub(r'\n ', '\n', text)

    return text.strip()


# ============================================================
#                    CHUNKING
# ============================================================

def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[Dict[str, Any]]:
    """
    Split text into overlapping chunks.
    """
    if not text or not text.strip():
        return []

    _validate_chunk_parameters(chunk_size, chunk_overlap)

    chunks: List[Dict[str, Any]] = []
    text_length = len(text)
    start = 0

    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = text[start:end].strip()

        if chunk:
            chunks.append({
                "chunk_id": len(chunks),
                "page_number": 1,           # TXT/MD files don't have real pages
                "text": chunk,
                "char_count": len(chunk),
            })

        start += chunk_size - chunk_overlap
        if start >= text_length:
            break

    return chunks


# ============================================================
#                    MAIN PROCESSING FUNCTION
# ============================================================

def process_txt(
    file_path: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200
) -> Dict[str, Any]:
    """
    Main function to process a .txt or .md file end-to-end.
    """
    start_time = time.time()
    file_path_obj = Path(file_path)

    # Validate parameters first
    _validate_chunk_parameters(chunk_size, chunk_overlap)

    logger.info(f"Starting TXT/MD processing: {file_path_obj.name}")

    if not _is_valid_text_file(file_path_obj):
        raise FileNotFoundError(
            f"File not found or unsupported format (only .txt and .md allowed): {file_path}"
        )

    try:
        # Step 1: Read file
        raw_text = _read_file_with_encoding(file_path_obj)

        if not raw_text.strip():
            logger.warning(f"File is empty: {file_path_obj.name}")
            return {
                "file_info": {
                    "filename": file_path_obj.name,
                    "file_path": str(file_path_obj),
                    "file_type": file_path_obj.suffix.lower(),
                },
                "processing": {
                    "chunk_size": chunk_size,
                    "chunk_overlap": chunk_overlap,
                    "total_chunks_created": 0,
                    "processing_time_seconds": 0,
                },
                "chunks": [],
                "stats": {
                    "total_chunks": 0,
                    "processing_time_seconds": 0,
                    "has_text_content": False,
                }
            }

        # Step 2: Clean text
        cleaned_text = clean_text(raw_text)

        # Step 3: Chunk text
        chunks = chunk_text(cleaned_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        processing_time = round(time.time() - start_time, 2)

        result = {
            "file_info": {
                "filename": file_path_obj.name,
                "file_path": str(file_path_obj),
                "file_type": file_path_obj.suffix.lower(),
            },
            "processing": {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "total_chunks_created": len(chunks),
                "processing_time_seconds": processing_time,
            },
            "chunks": chunks,
            "stats": {
                "total_chunks": len(chunks),
                "processing_time_seconds": processing_time,
                "has_text_content": len(cleaned_text) > 0,
            }
        }

        logger.info(
            f"Finished processing '{file_path_obj.name}' → "
            f"{len(chunks)} chunks | {processing_time}s"
        )

        return result

    except Exception as e:
        logger.error(f"Failed to process file '{file_path_obj.name}': {str(e)}")
        raise