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


def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap:int = 200, min_chunk_size: int = 100) -> List[Dict[str, Any]]:

    """
    Splits cleaned text into overlapping chunks using a simple recursive approach.

    Tries to break at paragraph or sentence level when possible to maintain context.
    """
    
    if not text or not text.strip():
        return []

    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    chunks = []
    start = 0
    text_length = len(text)
    current_page = 1

    while start < text_length:
        end = start + chunk_size

        # If remaining text is smaller than chunk_size, take it as the last chunk
        if end >= text_length:
            chunk = text[start:].strip()
            if len(chunk) >= min_chunk_size:
                chunks.append({
                    "chunk_id": len(chunks),
                    "page_number": current_page,
                    "text": chunk,
                    "char_count": len(chunk)
                })
            break

        chunk = text[start:end]

        # Try to break at paragraph level first
        last_para = chunk.rfind('\n\n')
        if last_para > chunk_size * 0.5:
            end = start + last_para
            chunk = text[start:end].strip()
        else:
            # Otherwise try to break at sentence level
            last_period = chunk.rfind('. ')
            if last_period > chunk_size * 0.5:
                end = start + last_period + 1
                chunk = text[start:end].strip()
        
        if len(chunk) >= min_chunk_size:
            chunks.append({
                "chunk_id": len(chunks),
                "page_number": current_page,
                "text": chunk,
                "char_count": len(chunk)
            })

        # Update current page if we passed a page marker
        page_markers = list(re.finditer(r'--- Page (\d+) ---', text[start:end]))
        if page_markers:
            current_page = int(page_markers[-1].group(1))

        # Move forward with overlap
        start = end - chunk_overlap
        if start <= 0:
            start = end
        
    return chunks

