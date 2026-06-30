"""
SEC EDGAR Text Filing Processor
Handles .txt filings downloaded from SEC EDGAR (Inline XBRL format)
"""

import re
from typing import List, Dict, Any, Optional
from pathlib import Path

from bs4 import BeautifulSoup
import html2text
from langchain_core.documents import Document


def extract_sec_header_metadata(content: str) -> Dict[str, Any]:
    """Extract useful metadata from SEC-HEADER section."""
    metadata = {
        "company_name": None,
        "cik": None,
        "filing_type": None,
        "period_of_report": None,
        "filed_as_of_date": None,
        "accession_number": None,
    }

    # Company name
    company_match = re.search(r"COMPANY CONFORMED NAME:\s+(.+)", content)
    if company_match:
        metadata["company_name"] = company_match.group(1).strip()

    # CIK
    cik_match = re.search(r"CENTRAL INDEX KEY:\s+(\d+)", content)
    if cik_match:
        metadata["cik"] = cik_match.group(1).strip()

    # Filing type
    form_match = re.search(r"CONFORMED SUBMISSION TYPE:\s+(.+)", content)
    if form_match:
        metadata["filing_type"] = form_match.group(1).strip()

    # Period of report
    period_match = re.search(r"CONFORMED PERIOD OF REPORT:\s+(\d+)", content)
    if period_match:
        metadata["period_of_report"] = period_match.group(1).strip()

    # Filed as of date
    filed_match = re.search(r"FILED AS OF DATE:\s+(\d+)", content)
    if filed_match:
        metadata["filed_as_of_date"] = filed_match.group(1).strip()

    # Accession number
    acc_match = re.search(r"ACCESSION NUMBER:\s+(.+)", content)
    if acc_match:
        metadata["accession_number"] = acc_match.group(1).strip()

    return metadata


def extract_main_document_text(content: str) -> Optional[str]:
    """
    Find the main 10-K / 10-Q document block (not exhibits).
    Looks for the block that has <TYPE>10-K or <TYPE>10-Q.
    """
    # Find all DOCUMENT blocks
    doc_blocks = re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", content, re.DOTALL)

    for block in doc_blocks:
        # Check if this block is the main filing (10-K or 10-Q)
        type_match = re.search(r"<TYPE>(10-K|10-Q)", block, re.IGNORECASE)
        if type_match:
            text_match = re.search(r"<TEXT>(.*?)</TEXT>", block, re.DOTALL)
            if text_match:
                return text_match.group(1).strip()

    # Fallback: if nothing found, try the first block anyway
    if doc_blocks:
        text_match = re.search(r"<TEXT>(.*?)</TEXT>", doc_blocks[0], re.DOTALL)
        if text_match:
            return text_match.group(1).strip()

    return None

def clean_and_convert_to_text(html_content: str) -> str:
    """
    Convert HTML + Inline XBRL to clean text.
    Less aggressive cleaning so we don't lose content.
    """
    # Only remove the outer XBRL wrapper if it exists, keep inner HTML
    html_content = re.sub(r"</?XBRL>", "", html_content, flags=re.IGNORECASE)

    soup = BeautifulSoup(html_content, "lxml")

    # Remove only script/style
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    h = html2text.HTML2Text()
    h.ignore_links = True
    h.ignore_images = True
    h.body_width = 0
    h.single_line_break = True

    text = h.handle(str(soup))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    """Simple paragraph-aware chunking."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk += para + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = para + "\n\n"

    if current_chunk:
        chunks.append(current_chunk.strip())

    final_chunks = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            final_chunks.append(chunk)
        else:
            prev = chunks[i - 1]
            overlap_text = prev[-overlap:] if len(prev) > overlap else prev
            final_chunks.append(overlap_text + "\n\n" + chunk)

    return final_chunks


def process_sec_filing(file_path: str) -> List[Document]:
    """Main function to process an SEC EDGAR .txt filing."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    print(f"Processing SEC filing: {file_path.name}")

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    header_metadata = extract_sec_header_metadata(content)
    main_text = extract_main_document_text(content)

    if not main_text:
        print(f"Warning: Could not extract main document from {file_path.name}")
        return []

    clean_text = clean_and_convert_to_text(main_text)

    if not clean_text or len(clean_text) < 500:
        print(f"Warning: Very little readable text extracted from {file_path.name}")
        return []

    text_chunks = chunk_text(clean_text, chunk_size=1500, overlap=200)

    documents = []
    for i, chunk in enumerate(text_chunks):
        doc = Document(
            page_content=chunk,
            metadata={
                "source": str(file_path),
                "file_name": file_path.name,
                "chunk_index": i,
                "total_chunks": len(text_chunks),
                "company_name": header_metadata.get("company_name"),
                "cik": header_metadata.get("cik"),
                "filing_type": header_metadata.get("filing_type"),
                "period_of_report": header_metadata.get("period_of_report"),
                "filed_as_of_date": header_metadata.get("filed_as_of_date"),
                "accession_number": header_metadata.get("accession_number"),
                "doc_type": "sec_filing",
            }
        )
        documents.append(doc)

    print(f"Extracted {len(documents)} chunks from {file_path.name}")
    return documents


if __name__ == "__main__":
    # Quick test
    test_file = "/Users/amritanshudash/Desktop/LedgerMind/data/raw/sec-edgar-filings/AAPL/10-K/0000320193-24-000123/full-submission.txt"
    docs = process_sec_filing(test_file)
    if docs:
        print("\n=== Sample Chunk 1 ===")
        print(docs[0].page_content[:1500])
        print("\n=== Metadata ===")
        print(docs[0].metadata)