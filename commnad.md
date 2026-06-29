Command,What It Should Do
python run.py data/,Ingest all PDFs from the data/ folder
python run.py data/file1.pdf,Ingest only this one PDF
python run.py data/file1.pdf data/file2.pdf,Ingest only these specific PDFs
python run.py --check,Global health check of everything in the DB
python run.py --check data/,Check health of all PDFs inside the data/ folder
python run.py --check data/file.pdf,Check only this specific PDF
python run.py --reset data/,Reset DB + re-ingest all PDFs from the folder
python run.py --reset data/file.pdf,Reset + re-ingest only this file