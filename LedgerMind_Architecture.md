# LedgerMind - Technical Architecture Document

## 1. Document Information
- **Document Version**: 1.0
- **Last Updated**: June 2026
- **Status**: Draft
- **Related Documents**: LedgerMind_Vision.md, LedgerMind_Requirements.md

## 2. Architecture Overview

LedgerMind follows a **Retrieval-Augmented Generation (RAG)** architecture. The system takes financial documents as input, processes them, stores them in a searchable format, and answers user questions with source citations.

### High-Level Architecture
[User]
↓
[Web Interface / Streamlit]
↓
[Query Processing]
↓
[Retriever] ←→ [Vector Database]
↓
[Context + Prompt] → [LLM]
↓
[Answer + Source Citation] → [User]


## 3. Core Components

| Component              | Responsibility                                      | Technology Options                  | Chosen Tech (To be decided) |
|------------------------|-----------------------------------------------------|-------------------------------------|-----------------------------|
| Document Upload        | Allow users to upload PDF files                     | Streamlit / FastAPI                 | -                           |
| Text Extraction        | Extract text from PDFs                              | pdfplumber, PyMuPDF, pdfminer       | -                           |
| Text Preprocessing     | Clean and chunk text                                | LangChain Text Splitters            | -                           |
| Embeddings             | Convert text chunks into vectors                    | sentence-transformers, OpenAI, Voyage | -                           |
| Vector Database        | Store and search embeddings                         | ChromaDB, FAISS, Pinecone           | -                           |
| Retriever              | Fetch relevant chunks based on user query           | LangChain Retriever                 | -                           |
| LLM                    | Generate answers using retrieved context            | Groq (Llama3), OpenAI, Claude       | -                           |
| User Interface         | Web interface for interaction                       | Streamlit                           | -                           |

## 4. Data Flow

### 4.1 Ingestion Flow (Document Upload)
1. User uploads a PDF document
2. Text is extracted from the PDF
3. Text is cleaned and split into chunks
4. Each chunk is converted into embeddings
5. Embeddings + metadata (page number, section) are stored in Vector Database

### 4.2 Query Flow (Question Answering)
1. User asks a question through the interface
2. Question is converted into embeddings
3. Relevant chunks are retrieved from Vector Database using similarity search
4. Retrieved chunks + user question are sent to the LLM as context
5. LLM generates an answer
6. Answer is returned to the user along with source citations (Page + Section)

## 5. Technology Stack (Proposed)

| Layer                    | Technology                  | Reason |
|--------------------------|-----------------------------|--------|
| Programming Language     | Python                      | Best ecosystem for AI/ML and RAG |
| Web Framework            | Streamlit                   | Fastest way to build UI for AI apps |
| PDF Processing           | pdfplumber + LangChain      | Good text extraction + chunking |
| Embeddings               | sentence-transformers       | Free, local, good quality |
| Vector Database          | ChromaDB                    | Easy to use, works well locally |
| LLM                      | Groq (Llama 3.1 or Mixtral) | Fast inference + generous free tier |
| Orchestration            | LangChain                   | Standard framework for RAG pipelines |
| Version Control          | Git + GitHub                | Code management and portfolio |

## 6. Design Decisions & Trade-offs

| Decision                    | Chosen Option       | Alternative Considered     | Reason |
|----------------------------|---------------------|----------------------------|--------|
| UI Framework               | Streamlit           | Gradio, FastAPI + React    | Faster development for MVP |
| Vector Database            | ChromaDB            | FAISS, Pinecone            | Simpler setup for solo project |
| LLM                        | Groq                | OpenAI, Local models       | Speed + Cost + Free tier |
| Embeddings                 | Local (sentence-transformers) | OpenAI embeddings     | Cost control + offline capability |

## 7. Scalability Considerations (Future)
- ChromaDB can be replaced with Pinecone or Weaviate if needed
- Can move from Streamlit to FastAPI + React for better performance
- Can add caching for frequently asked questions

## 8. Security Considerations
- User documents should be processed securely
- If deployed publicly, user data should not be stored permanently without consent
- API keys should be handled using environment variables

## 9. Open Questions
- Should we support multiple documents per session?
- Should we allow users to delete uploaded documents?
- Do we want to add basic conversation memory in the first version?

## 10. Future Improvements
- Add support for scanned PDFs using OCR
- Add better citation with actual text snippets or page screenshots
- Improve retrieval using metadata filtering and hybrid search

---

**End of Architecture Document**