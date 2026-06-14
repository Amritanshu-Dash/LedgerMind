import pdfplumber
import pandas as pd
from typing import List, Dict, Any, Optional
from pathlib import Path
import re

def extract_text_and_tables(pdf_path: str) -> Dict[str, Any]:
    
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
                    full_text.append(f"--- Page {page_num} ---\n{page_text}")

                #Extract tables from current page
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
    
    if not raw_text or not isinstance(raw_text, str):
        return ""
    
    text = raw_text
    
    text = re.sub(r'-\s*\n\s*', '', text)
    text = re.sub(r'-\s+', '', text)

    if remove_page_markers:
        text = re.sub(r'---\s*Page\s+\d+\s*---', '', text)

    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)

    text = re.sub(r' \n', '\n', text)
    text = re.sub(r'\n ', '\n', text)

    text = text.strip()

    return text


def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap:int = 200, min_chunk_size: int = 100) -> List[Dict[str, Any]]:
    
    if not text or not text.strip():
        return []

    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        if end >= text_length:
            chunk = text[start:].strip()
            if len(chunk) >= min_chunk_size:
                chunks.append({
                    "chunk_id": len(chunks),
                    "text": chunk,
                    "char_count": len(chunk)
                })
            break

        chunk = text[start:end]

        last_para = chunk.rfind('\n\n')
        if last_para > chunk_size * 0.5:
            end = start + last_para
            chunk = text[start:end].strip()
        else:
            last_period = chunk.rfind('. ')
            if last_period > chunk_size * 0.5:
                end = start + last_period + 1
                chunk = text[start:end].strip()
        
        if len(chunk) >= min_chunk_size:
            chunks.append({
                "chunk_id": len(chunks),
                "text": chunk,
                "char_count": len(chunk)
            })
        start = end - chunk_overlap
        if start <= 0:
            start = end
        
    return chunks

#call 

result = extract_text_and_tables("/Users/amritanshudash/Desktop/LedgerMind/EX-21.1.pdf")

print(result["text"])           # Full extracted text
print(result["metadata"])       # PDF info
print(len(result["tables"]))    # Number of tables found

# Access first table
if result["tables"]:
    print(result["tables"])  


print("Clenaedddddddddddd")
# Basic usage (keeps page markers)
cleaned_text = clean_extracted_text(result["text"])

# If you want to remove page markers
cleaned_text = clean_extracted_text(result["text"], remove_page_markers=True)

print(cleaned_text)


print("\n\nchunkkkkkkkkkkkkkkkkkkkkkk\n\n")

chunks = chunk_text(cleaned_text, chunk_size=1000, chunk_overlap=200)

print(f"Total chunks created: {len(chunks)}")
print(chunks[0]["text"])        # First chunk
print(chunks[0]["char_count"])  # Size of first chunk