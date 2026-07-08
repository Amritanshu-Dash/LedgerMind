"""
Test Script for txt_ingestion.py
================================
Use this to test TXT and Markdown file processing.
"""

from txt_file_ingestion import process_txt
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)


def test_normal_txt_file(file_path: str):
    """Test normal .txt file processing."""
    print("\n" + "="*60)
    print("TEST 1: Normal TXT File Processing")
    print("="*60)
    
    result = process_txt(file_path, chunk_size=1000, chunk_overlap=200)
    
    print(f"\nFile: {result['file_info']['filename']}")
    print(f"File Type: {result['file_info']['file_type']}")
    print(f"Total Chunks: {result['stats']['total_chunks']}")
    print(f"Processing Time: {result['stats']['processing_time_seconds']}s")
    print(f"Has Text Content: {result['stats']['has_text_content']}")


def test_markdown_file(file_path: str):
    """Test .md (Markdown) file processing."""
    print("\n" + "="*60)
    print("TEST 2: Markdown (.md) File Processing")
    print("="*60)
    
    result = process_txt(file_path, chunk_size=800, chunk_overlap=150)
    
    print(f"\nFile: {result['file_info']['filename']}")
    print(f"Total Chunks: {result['stats']['total_chunks']}")
    if result["chunks"]:
        print("First chunk preview:")
        print(result["chunks"][0]["text"][:400])


def test_edge_cases():
    """Test error handling."""
    print("\n" + "="*60)
    print("TEST 3: Edge Case Handling")
    print("="*60)
    
    # Non-existent file
    try:
        process_txt("this_file_does_not_exist.txt")
    except FileNotFoundError:
        print("✓ Caught FileNotFoundError correctly")
    
    # Invalid chunk_size
    try:
        process_txt("dummy.txt", chunk_size=0)
    except ValueError as e:
        print(f"✓ Caught ValueError for chunk_size: {e}")
    
    # Invalid chunk_overlap
    try:
        process_txt("dummy.txt", chunk_size=500, chunk_overlap=600)
    except ValueError as e:
        print(f"✓ Caught ValueError for chunk_overlap: {e}")


if __name__ == "__main__":
    # ====================== UPDATE THESE PATHS ======================
    txt_file = "data/raw/sec-edgar-filings/AAPL/10-K/0000320193-24-000123/full-submission.txt"          # ← Change this
    md_file = "/path/to/your/test_file.md"            # ← Change this (optional)
    # ==============================================================

    test_normal_txt_file(txt_file)
    
    # Only run markdown test if you have a .md file
    # test_markdown_file(md_file)
    
    test_edge_cases()

    print("\n" + "="*60)
    print("All TXT/MD tests completed.")
    print("="*60)