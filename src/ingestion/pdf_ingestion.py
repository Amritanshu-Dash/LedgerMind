"""
PDF Text Ingestion Module
=========================
Robust and production-ready module for processing PDF files.
"""

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pdfplumber

# ============================================================
#                        LOGGING
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
#                    VALIDATION & HELPERS
# ============================================================

def _validate_chunk_parameters(chunk_size: int, chunk_overlap: int) -> None:
    """Validate chunking parameters strictly."""
    if not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError(f"chunk_size must be a positive integer, got {chunk_size}")
    if not isinstance(chunk_overlap, int) or chunk_overlap < 0:
        raise ValueError(f"chunk_overlap must be a non-negative integer, got {chunk_overlap}")
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be smaller than chunk_size ({chunk_size})"
        )


def _is_valid_pdf(pdf_path: Path) -> bool:
    """Check if path points to a valid PDF file."""
    return pdf_path.is_file() and pdf_path.suffix.lower() == ".pdf"


# ============================================================
#                    CORE EXTRACTION
# ============================================================

def extract_text_and_tables(pdf_path: str) -> Dict[str, Any]:
    """
    Extract text and tables from PDF using pdfplumber.
    """
    pdf_path = Path(pdf_path)

    if not _is_valid_pdf(pdf_path):
        raise FileNotFoundError(f"Invalid or missing PDF file: {pdf_path}")

    logger.info(f"Extracting content from: {pdf_path.name}")

    full_text: List[str] = []
    all_tables: List[pd.DataFrame] = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) == 0:
                logger.warning(f"PDF has no pages: {pdf_path.name}")
                return {
                    "text": "",
                    "tables": [],
                    "metadata": {
                        "filename": pdf_path.name,
                        "total_pages": 0,
                        "total_tables_found": 0,
                        "pdf_path": str(pdf_path),
                    },
                }

            for page_num, page in enumerate(pdf.pages, start=1):
                try:
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        full_text.append(f"\n\n--- Page {page_num} ---\n{page_text}")
                except Exception:
                    continue

                try:
                    page_tables = page.extract_tables()
                    if page_tables:
                        for table in page_tables:
                            if len(table) > 1:
                                try:
                                    df = pd.DataFrame(table[1:], columns=table[0])
                                    all_tables.append(df)
                                except Exception:
                                    continue
                except Exception:
                    continue

        metadata = {
            "filename": pdf_path.name,
            "total_pages": len(pdf.pages),
            "total_tables_found": len(all_tables),
            "pdf_path": str(pdf_path),
        }

        return {
            "text": "\n".join(full_text),
            "tables": all_tables,
            "metadata": metadata,
        }

    except pdfplumber.pdfminer.pdfparser.PDFSyntaxError:
        raise RuntimeError(f"Corrupted or invalid PDF file: {pdf_path.name}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error while processing '{pdf_path.name}': {str(e)}")


# ============================================================
#                    TEXT CLEANING
# ============================================================

def clean_extracted_text(raw_text: str, remove_page_markers: bool = False) -> str:
    """
    Clean and normalize extracted PDF text.
    """
    if not raw_text or not isinstance(raw_text, str):
        return ""

    text = raw_text

    # Fix hyphenated words
    text = re.sub(r'-\s*\n\s*', '', text)
    text = re.sub(r'-\s+', '', text)

    # Remove page markers
    if remove_page_markers:
        # This pattern handles different variations like:
        # --- Page 1 ---, --Page 1--, ---Page 1--- etc.
        text = re.sub(r'-{2,}\s*Page\s*\d+\s*-{2,}', '', text, flags=re.IGNORECASE)

    # Normalize whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

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
    Split text into overlapping chunks while preserving page numbers.
    """
    if not text or not text.strip():
        return []

    _validate_chunk_parameters(chunk_size, chunk_overlap)

    chunks: List[Dict[str, Any]] = []
    page_pattern = re.compile(r'--- Page (\d+) ---')

    parts = page_pattern.split(text)
    page_contents: List[tuple] = []

    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            try:
                page_num = int(parts[i])
                content = parts[i + 1] if (i + 1) < len(parts) else ""
                if content.strip():
                    page_contents.append((page_num, content))
            except (ValueError, IndexError):
                continue
    else:
        page_contents.append((1, text))

    for page_num, page_text in page_contents:
        if not page_text.strip():
            continue

        start = 0
        text_length = len(page_text)

        while start < text_length:
            end = min(start + chunk_size, text_length)
            chunk = page_text[start:end].strip()

            if chunk:
                chunks.append({
                    "chunk_id": len(chunks),
                    "page_number": page_num,
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

def process_pdf(
    pdf_path: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    remove_page_markers: bool = False
) -> Dict[str, Any]:
    """
    Main function to process a PDF file end-to-end.
    """
    start_time = time.time()
    pdf_path_obj = Path(pdf_path)

    # === VALIDATE PARAMETERS FIRST (before checking file) ===
    _validate_chunk_parameters(chunk_size, chunk_overlap)

    logger.info(f"Starting PDF processing: {pdf_path_obj.name}")

    if not _is_valid_pdf(pdf_path_obj):
        raise FileNotFoundError(f"PDF file not found or invalid: {pdf_path}")

    try:
        extraction = extract_text_and_tables(str(pdf_path_obj))

        cleaned_text = clean_extracted_text(
            extraction["text"], 
            remove_page_markers=remove_page_markers
        )

        chunks = chunk_text(cleaned_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        processing_time = round(time.time() - start_time, 2)

        result = {
            "file_info": {
                "filename": extraction["metadata"]["filename"],
                "pdf_path": extraction["metadata"]["pdf_path"],
                "total_pages": extraction["metadata"]["total_pages"],
            },
            "extraction": {
                "raw_text_length": len(extraction["text"]),
                "cleaned_text_length": len(cleaned_text),
                "total_tables_extracted": len(extraction["tables"]),
            },
            "processing": {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "total_chunks_created": len(chunks),
                "processing_time_seconds": processing_time,
            },
            "chunks": chunks,
            "tables": extraction["tables"],
            "stats": {
                "total_pages": extraction["metadata"]["total_pages"],
                "total_tables": len(extraction["tables"]),
                "total_chunks": len(chunks),
                "processing_time_seconds": processing_time,
                "has_text_content": len(cleaned_text) > 0,
            }
        }

        logger.info(
            f"Finished processing '{pdf_path_obj.name}' → "
            f"{len(chunks)} chunks | {result['stats']['total_tables']} tables | "
            f"{processing_time}s"
        )

        return result

    except Exception as e:
        logger.error(f"Failed to process PDF '{pdf_path_obj.name}': {str(e)}")
        raise