"""
vector_store.py
Handles embedding generation and storage/retrieval using ChromaDB.
"""

import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path
from typing import List, Dict, Any, Optional


class VectorStore:
    def __init__(self, persist_directory: str = "vector_db", collection_name: str = "ledgermind_docs"):
        """
        Initialize ChromaDB client and collection.
        Uses sentence-transformers for local embeddings.
        """
        self.persist_directory = persist_directory
        self.client = chromadb.PersistentClient(path=persist_directory)

        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )

        try:
            self.collection = self.client.get_collection(name=collection_name)
            print(f"✅ Vector store initialized. Collection: '{collection_name}'")
        except Exception:
            self.collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.embedding_function,
                metadata={"hnsw:space": "cosine"}
            )
            print(f"✅ Created new collection: '{collection_name}'")

    def add_chunks(self, chunks: List[Dict[str, Any]], source_filename: str) -> None:
        """Add chunks with embeddings + all metadata to the vector store."""
        if not chunks:
            print("⚠️ No chunks to add.")
            return

        documents = []
        metadatas = []
        ids = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{source_filename}_chunk_{i}"

            # Support both {"text": ..., "metadata": {...}} and flat dict
            meta = chunk.get("metadata", chunk)

            # Base metadata
            base_meta = {
                "source": source_filename,
                "chunk_id": i,
                "page_number": meta.get("page_number", -1),
                "char_count": meta.get("char_count", len(chunk.get("text", ""))),
            }

            # Add all extra metadata from SEC filings (company_name, filing_type, etc.)
            extra_meta = {k: v for k, v in meta.items() 
                        if k not in ["page_number", "char_count", "source"]}

            documents.append(chunk["text"])
            metadatas.append({**base_meta, **extra_meta})
            ids.append(chunk_id)

        self.collection.add(documents=documents, metadatas=metadatas, ids=ids)
        print(f"✅ Added {len(chunks)} chunks from '{source_filename}' to vector store.")

    def query(self, query_text: str, n_results: int = 5, filter_metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Retrieve the most relevant chunks for a given query."""
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=filter_metadata,
            include=["documents", "metadatas", "distances"]
        )
        return results

    def get_collection_stats(self) -> Dict[str, Any]:
        """Get basic stats about the collection."""
        count = self.collection.count()
        return {
            "collection_name": self.collection.name,
            "total_chunks": count,
            "persist_directory": str(self.persist_directory)
        }

    def delete_document(self, source_filename: str) -> int:
        """Delete all chunks belonging to a specific source."""
        try:
            existing = self.collection.get(where={"source": source_filename})
            count = len(existing["ids"]) if existing.get("ids") else 0
            if count > 0:
                self.collection.delete(where={"source": source_filename})
                print(f"🧹 Deleted {count} old chunks for '{source_filename}'")
            return count
        except Exception as e:
            print(f"Warning: Could not delete document - {e}")
            return 0

    def reset_collection(self) -> None:
        """Completely reset the collection."""
        collection_name = self.collection.name
        try:
            self.client.delete_collection(name=collection_name)
        except Exception:
            pass

        self.collection = self.client.create_collection(
            name=collection_name,
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"}
        )
        print(f"⚠️ Collection '{collection_name}' has been fully reset.")

    def get_document_info(self, source_filename: str) -> dict:
        """
        Check if a document exists and return info + sample metadata.
        """
        try:
            results = self.collection.get(where={"source": source_filename}, limit=1)
            ids = results.get("ids", [])

            if not ids:
                return {"exists": False, "chunk_count": 0, "healthy": False}

            full_results = self.collection.get(where={"source": source_filename})
            chunk_count = len(full_results.get("ids", []))

            sample_meta = results.get("metadatas", [{}])[0] if results.get("metadatas") else {}

            return {
                "exists": True,
                "chunk_count": chunk_count,
                "healthy": True,
                "sample_metadata": {
                    "company_name": sample_meta.get("company_name"),
                    "cik": sample_meta.get("cik"),
                    "filing_type": sample_meta.get("filing_type"),
                    "period_of_report": sample_meta.get("period_of_report"),
                    "accession_number": sample_meta.get("accession_number"),
                }
            }
        except Exception as e:
            return {"exists": False, "error": str(e), "healthy": False}

    def list_documents(self) -> list:
        """Return a list of all unique source filenames in the database."""
        try:
            results = self.collection.get()
            sources = set()
            for meta in results.get("metadatas", []):
                if meta and "source" in meta:
                    sources.add(meta["source"])
            return sorted(list(sources))
        except Exception as e:
            print(f"Error while listing documents: {e}")
            return []


# ====================== Quick Test ======================
if __name__ == "__main__":
    vs = VectorStore(persist_directory="vector_db", collection_name="test_collection")
    sample_chunks = [
        {"text": "Apple Hospitality REIT is a real estate investment trust.", "page_number": 1},
        {"text": "The company owns and operates hotels across the United States.", "page_number": 1},
    ]
    vs.add_chunks(sample_chunks, source_filename="test.pdf")
    print(vs.get_collection_stats())