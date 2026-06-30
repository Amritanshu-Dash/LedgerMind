from sec_edgar_downloader import Downloader
from pathlib import Path

# ====================== CONFIG ======================
COMPANIES = [
    "AAPL",   # Apple
    "MSFT",   # Microsoft
    "GOOGL",  # Google (Alphabet)
    "AMZN",   # Amazon
    "NVDA",   # Nvidia
    "TSLA",   # Tesla
    "META",   # Meta
    "ADBE",   # Adobe
    "INTC",   # Intel
    "CSCO",   # Cisco
]

# What filings you want to download
FILING_TYPES = ["10-K", "10-Q"]

# How many recent filings per type (1 = latest only)
NUM_FILINGS = 2

# Folder where files will be saved
DOWNLOAD_DIR = "data/raw"
# ===================================================


def main():
    print("🚀 Starting SEC EDGAR Downloader...\n")

    dl = Downloader("LedgerMind", "####", Path(DOWNLOAD_DIR))

    for ticker in COMPANIES:
        print(f"\n{'='*60}")
        print(f"Downloading filings for: {ticker}")
        print(f"{'='*60}")

        for filing_type in FILING_TYPES:
            try:
                dl.get(
                    filing_type,
                    ticker,
                    limit=NUM_FILINGS,
                    download_details=False
                )
                print(f"✅ {filing_type} downloaded for {ticker}")
            except Exception as e:
                print(f"❌ Failed to download {filing_type} for {ticker}: {e}")

    print("\n🎉 All downloads completed!")
    print(f"Files saved in: {DOWNLOAD_DIR}/")


if __name__ == "__main__":
    main()