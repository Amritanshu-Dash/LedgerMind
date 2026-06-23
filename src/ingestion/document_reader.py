import pdfplumber
import pandas as pd
from typing import List, Dict, Any, Optional
from pathlib import Path
import re
import time

def extract_text_and_tables(pdf_path: str) -> Dict[str, Any]:

    """
    Extracts text and tables from a PDF file using pdfplumber.

    Adds page markers (--- Page X ---) to help maintain document structure.
    Tables are converted into pandas DataFrames for easier handling later.
    """
    
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    full_text = [] 
    all_tables: List[pd.DataFrame] = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate (pdf.pages, start = 1): #start from page = 1 for better readability 
                #Extract text from current page
                page_text = page.extract_text()
                if page_text:
                    full_text.append(f"\n\n--- Page {page_num} ---\n{page_text}")

                #Extract tables from current page and convert them to dataframes
                page_tables = page.extract_tables()
                if page_tables:
                    for table in page_tables:
                        if len(table) > 1: #At least header + one row
                            try:
                                df = pd.DataFrame(table[1:], columns=table[0])
                                all_tables.append(df)
                            except Exception as e:
                                print(f"Error creating DataFrame from table on page {page_num}: {e}")
            
            #Prepare metadata
            metadata = {
                "filename": pdf_path.name,
                "total_pages": len(pdf.pages),
                "total_tables_found": len(all_tables),
                "pdf_path": str(pdf_path)
            }

            return {
                "text": "\n".join(full_text),
                "tables": all_tables,
                "metadata": metadata
            }
    except Exception as e:
        raise RuntimeError(f"An error occurred while processing the PDF: {e}")              


def clean_extracted_text(raw_text: str, remove_page_markers: bool = False) -> str:

    """
    Cleans and normalizes raw text extracted from PDF.

    Handles hyphenated words, excessive whitespace, and optionally removes page markers.
    """
    
    if not raw_text or not isinstance(raw_text, str):
        return ""
    
    text = raw_text
    
    # Fix hyphenated words broken across lines (e.g., "infor- mation")
    text = re.sub(r'-\s*\n\s*', '', text)
    text = re.sub(r'-\s+', '', text)

    # Remove page markers if requested
    if remove_page_markers:
        text = re.sub(r'---\s*Page\s+\d+\s*---', '', text)

    # Normalise excessive newlines and spaces
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    # Strip whitespaces from each line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)

    #Final cleanup of spaces around newlines
    text = re.sub(r' \n', '\n', text)
    text = re.sub(r'\n ', '\n', text)

    text = text.strip()

    return text


def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap:int = 200) -> List[Dict[str, Any]]:

    """
    Splits cleaned text into overlapping chunks using a simple recursive approach.

    Tries to break at paragraph or sentence level when possible to maintain context.
    """
    
    if not text or not text.strip():
        return []

    chunks: List[Dict[str, Any]] = []
    page_pattern = re.compile(r'--Page\s+(\d+)\s*--')

    # Split text using page markers
    parts = page_pattern.split(text)

    page_contents = []

    if len(parts) > 1:
        # Page markers exist
        for i in range(1, len(parts), 2):
            try:
                page_num = int(parts[i])
                page_content = parts[i + 1] if (i + 1) < len(parts) else ""
                if page_content.strip():
                    page_contents.append((page_num, page_content))
            except (ValueError, IndexError):
                continue
    else:
        # No page markers found → treat everything as page 1
        page_contents.append((1, text))

    # Chunk each page separately
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
                    "char_count": len(chunk)
                })

            # Move window forward with overlap
            start += chunk_size - chunk_overlap

            if start >= text_length:
                break

    return chunks

