"""
Test Script for pdf_ingestion.py
"""

from pdf_ingestion import process_pdf
import logging

# Configure logging only in the test file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)

def test_normal_pdf(pdf_path: str):
    print("\n" + "="*60)
    print("TEST 1: Normal PDF Processing")
    print("="*60)
    
    result = process_pdf(pdf_path, chunk_size=1000, chunk_overlap=200)
    
    print(f"\nFile: {result['file_info']['filename']}")
    print(f"Total Pages: {result['file_info']['total_pages']}")
    print(f"Total Chunks: {result['stats']['total_chunks']}")
    print(f"Total Tables: {result['stats']['total_tables']}")
    print(f"Processing Time: {result['stats']['processing_time_seconds']}s")


def test_with_page_markers_removed(pdf_path: str):
    print("\n" + "="*60)
    print("TEST 2: Page Markers Removed")
    print("="*60)
    
    result = process_pdf(pdf_path, chunk_size=800, chunk_overlap=150, remove_page_markers=True)
    
    print(f"\nTotal Chunks: {result['stats']['total_chunks']}")
    if result["chunks"]:
        print("First chunk preview:")
        print(result["chunks"][0]["text"][:400])


def test_edge_cases():
    print("\n" + "="*60)
    print("TEST 3: Edge Case Handling")
    print("="*60)
    
    # Non-existent file
    try:
        process_pdf("this_file_does_not_exist.pdf")
    except FileNotFoundError as e:
        print(f"✓ Caught FileNotFoundError correctly")
    
    # Invalid chunk_size
    try:
        process_pdf("dummy.pdf", chunk_size=0)
    except ValueError as e:
        print(f"✓ Caught ValueError for invalid chunk_size: {e}")
    
    # Invalid chunk_overlap
    try:
        process_pdf("dummy.pdf", chunk_size=500, chunk_overlap=600)
    except ValueError as e:
        print(f"✓ Caught ValueError for invalid chunk_overlap: {e}")


if __name__ == "__main__":
    test_pdf = "/Users/amritanshudash/Desktop/LedgerMind/data/EX-21.1.pdf"

    test_normal_pdf(test_pdf)
    test_with_page_markers_removed(test_pdf)
    test_edge_cases()

    print("\n" + "="*60)
    print("All tests completed successfully.")
    print("="*60)