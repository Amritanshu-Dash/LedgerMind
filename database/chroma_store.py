"""
ChromaDB Vector Store
=====================
This module handles all interactions with ChromaDB.
It stores document chunks as embeddings and allows semantic search.
"""

import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

#Configure logging 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)

logger = logging.getLogger(__name__)

class ChromaStore:
    """
    A clean wrapper around ChromaDB for LedgerMind.
    """
    def __init__(self, persist_directory: str = "database/chroma_db", collection_name: str = "ledgermind", embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Initialize ChromaDB client and embedding model.
        """
        self.persist_directory = Path(persist_directory)
        self.collection_name = collection_name
        self.embedding_model_name = embedding_model_name

        #Create directory if it doesn't exist
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initializing ChromaDB at {self.persist_directory}")

        # Initialize ChromaDB client(persistent storage)
        self.client = chromadb.PersistentClient(
            path= str(self.persist_directory),
            settings = Settings(anonymized_telemetry=False)
        )

        #Load embedding model
        logger.info(f"Loading embedding model: {self.embedding_model_name}")
        self.embedding_model = SentenceTransformer(self.embedding_model_name)

        #Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"} # Cosine similarity for semantic search
        )

        logger.info(f"ChromaDB collection '{self.collection_name}' is ready.")

    def add_chunks(
            self,
            chunks: List[str],
            metadatas: Optional[List[Dict[str, Any]]] = None,
            ids: Optional[List[str]] = None
        ):
        """
        Add text chunks to ChromaDB after converting them to embeddings.
        """

        if not chunks:
            logger.warning("No chunks provided to add to ChromaDB.")
            return
        
        logger.info(f"Generating embeddings for {len(chunks)} chunks using model '{self.embedding_model_name}'...")

        # Generate embeddings
        embeddings = self.embedding_model.encode(chunks, show_progress_bar=True).tolist()

        # Create IDs if not provided 
        if ids is None:
            existing_count = self.collection.count()
            ids = [f"chunk_{existing_count + i}" for i in range(len(chunks))]
        
        #Create empty metadata if not provided
        if metadatas is None:
            metadatas = [{} for _ in chunks]

        # Add to ChromaDB collection
        self.collection.add(
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )

        logger.info(f"Successfully added {len(chunks)} chunks to ChromaDB collection '{self.collection_name}'.")

    
    def search(
            self,
            query: str,
            n_results: int = 5
        ) -> List[Dict[str, Any]]:
        """
        Perform a semantic search in ChromaDB for the given query.
        Returns a clean list of top results with document, metadata, and distance.
        """
        logger.info(f"Generating embedding for query: '{query}'")
        query_embedding = self.embedding_model.encode([query]).tolist()

        logger.info(f"Searching top {n_results} results in collection '{self.collection_name}'...")
        
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=n_results
        )

        # Format results into a clean list
        formatted_results = []
        for i in range(len(results["ids"][0])):
            formatted_results.append({
                "id": results["ids"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i]
            })

        logger.info(f"Search completed. Found {len(formatted_results)} results.")
        return formatted_results
    
    def get_collection_info(self) -> Dict[str, Any]:
        """
        Get basic information about the ChromaDB collection.
        """
        info = {
            "collection_name": self.collection_name,
            "total_chunks": self.collection.count(),
            "embedding_model": self.embedding_model_name,
            "persist_directory": str(self.persist_directory)
        }
        logger.info(f"Collection Info: {info}")
        return info
    
    def clear_collection(self) -> None:
        """
        Delete all documents by removing and recreating the collection.
        This is the most reliable way in current ChromaDB versions.
        """
        logger.warning(f"Clearing all documents from collection '{self.collection_name}'...")
        
        # Delete the old collection
        self.client.delete_collection(name=self.collection_name)
        
        # Recreate a fresh collection
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        
        logger.info("Collection cleared and recreated successfully.")


# ============================================================
#                      TESTING SECTION
# ============================================================
if __name__ == "__main__":
    print("\n" + "="*60)
    print("TESTING CHROMA STORE")
    print("="*60)

    # Initialize store
    store = ChromaStore()

    # Sample chunks for testing
    sample_chunks = [
        "Apple Inc. reported strong revenue growth in the fiscal year 2025.",
        "The company's services segment continues to be a major profit driver.",
        "iPhone sales remained stable despite global economic challenges.",
        "Apple is investing heavily in artificial intelligence and machine learning.",
        "The company maintains a strong cash position and returns capital to shareholders."
    ]

    sample_metadatas = [
        {"source": "Apple_10K_2025", "page": 12, "section": "Revenue"},
        {"source": "Apple_10K_2025", "page": 18, "section": "Services"},
        {"source": "Apple_10K_2025", "page": 25, "section": "Products"},
        {"source": "Apple_10K_2025", "page": 40, "section": "R&D"},
        {"source": "Apple_10K_2025", "page": 55, "section": "Capital Return"}
    ]

    # Add chunks
    store.add_chunks(chunks=sample_chunks, metadatas=sample_metadatas)

    # Show info
    info = store.get_collection_info()
    print(f"\nCollection Info: {info}")

    # Test search
    print("\nSearching for: 'What about Apple AI investment?'")
    results = store.search("What about Apple AI investment?", n_results=2)

    print("\nTop Results:")
    for i, result in enumerate(results):
        print(f"\n{i+1}. {result['document']}")
        print(f"   Metadata: {result['metadata']}")
        print(f"   Distance: {result['distance']:.4f}")

    print("\n" + "="*60)
    print("Testing completed successfully!")
    print("="*60)