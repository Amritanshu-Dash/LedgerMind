"""
vector_store.py
Handles embedding generation and storage/retrieval using ChromaDB.
"""

import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path
from typing import List, Dict, Any, Optional

class VectorStore:
    def __init__( self, persist_directory: str = "vector_db", collection_name: str = "documents", embdding_model: str = "all-MiniLM-L6-v2"):
        """
        Initialize ChromaDB client and collection.
        Uses sentence-transformers for local embeddings (free & good quality).
        """
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        # initialise chromdb with persistence
        self.client = chromadb.PersistentClient(path=str(self.persist_directory))

        # Use sentence-transformers embedding functions
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=embdding_model)

        #Get or create collections
        self.collection = self.client.get_or_create_collection(name=collection_name, embedding_function=self.embedding_function, metadata={"hnsw:space": "cosine"}) #Use cosine similarity

        print(f"✅ Vector store initialized. Collection: '{collection_name}'")


    def add_chunks(self, chunks: List[Dict[str, Any]], source_filename: str) -> None:

        """
        Add chunks with embeddings to the vector store.
        """

        if not chunks:
            print("⚠️ No chunks to add.")
            return
        
        documents = []
        metadatas = []
        ids = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{source_filename}_chunk_{i}"
            documents.append(chunk["text"])

            metadatas.append({"source": source_filename, "chunk_id": i, "page_number": chunk.get("page_number", -1), "char_count": chunk.get("char_count", len(chunk["text"]))})

            ids.append(chunk_id)

        #Add to chromeDB (automatically generates embeddings)
        self.collection.add(documents=documents, metadatas=metadatas, ids=ids)

        print(f"✅ Added {len(chunks)} chunks from '{source_filename}' to vector store.")


    def query(self, query_text: str, n_results: int = 5, filter_metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Retrieve the most relevant chunks for a given query.
        """

        results = self.collection.query(query_texts=[query_text], n_results=n_results, where=filter_metadata, include=["documents", "metadatas", "distances"])
        return results
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """Get basic stats about the collection."""
        count = self.collection.count()
        return {
            "collection_name": self.collection.name,
            "total_chunks": count,
            "persist_directory": str(self.persist_directory)
        }

# ====================== Quick Test ======================

if __name__ == "__main__":
    # Test the vector store
    vs = VectorStore(persist_directory="vector_db", collection_name="test_collection")

    # Sample chunks for testing
    sample_chunks = [
        {"text": "Apple Hospitality REIT is a real estate investment trust.", "page_number": 1, "char_count": 60},
        {"text": "The company owns and operates hotels across the United States.", "page_number": 1, "char_count": 65},
    ]

    vs.add_chunks(sample_chunks, source_filename="test.pdf")
    print(vs.get_collection_stats())
    