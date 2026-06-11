# LedgerMind - Development Roadmap

## 1. Document Information
- **Document Version**: 1.0
- **Last Updated**: June 2026
- **Status**: Draft
- **Related Documents**: LedgerMind_Vision.md, LedgerMind_Requirements.md, LedgerMind_Architecture.md

## 2. Project Overview
This roadmap breaks down the development of LedgerMind into logical phases. Each phase has clear goals, deliverables, and success criteria. The project will be executed phase by phase instead of trying to build everything at once.

## 3. Development Phases

### Phase 0: Project Setup & Documentation (Completed)
**Goal**: Set up the project foundation professionally.

**Deliverables**:
- GitHub repository created with proper structure
- Vision Document completed
- Requirements Document completed
- Architecture Document completed

**Status**: ✅ Completed

---

### Phase 1: Document Ingestion Pipeline
**Goal**: Build the foundation to upload and process financial PDFs.

**Key Features**:
- PDF upload functionality
- Text extraction from PDFs
- Text cleaning and preprocessing
- Text chunking with metadata (page number, section)

**Deliverables**:
- Working script/module that can take a PDF and convert it into clean chunks with metadata
- Basic testing with 2–3 financial PDFs

**Success Criteria**:
- Text is cleanly extracted from PDFs
- Chunks contain proper metadata (page number + heading if possible)
- Code is modular and well-documented

**Estimated Effort**: 2 – 3 weeks

---

### Phase 2: Embeddings + Vector Database
**Goal**: Convert chunks into vectors and store them for retrieval.

**Key Features**:
- Generate embeddings for text chunks
- Store embeddings + metadata in a vector database
- Basic retrieval functionality (similarity search)

**Deliverables**:
- Working embedding pipeline
- Vector database setup with stored documents
- Ability to query and retrieve relevant chunks

**Success Criteria**:
- Embeddings are generated successfully
- Relevant chunks are retrieved when querying
- Metadata is preserved during storage and retrieval

**Estimated Effort**: 1.5 – 2 weeks

---

### Phase 3: Basic RAG Pipeline (Question Answering)
**Goal**: Build the core intelligence — answer questions using retrieved context.

**Key Features**:
- Take user question
- Retrieve relevant chunks
- Send context + question to LLM
- Generate grounded answers

**Deliverables**:
- Working RAG pipeline
- Basic question-answering functionality
- Simple script/interface to test the system

**Success Criteria**:
- System can answer questions based on uploaded documents
- Answers are relevant to the document content
- Basic error handling is in place

**Estimated Effort**: 2 – 2.5 weeks

---

### Phase 4: Source Citation (Core Feature)
**Goal**: Implement the most important differentiator — showing sources with every answer.

**Key Features**:
- Capture and return page number with retrieved chunks
- Capture and return section/heading (if available)
- Display sources clearly with the final answer

**Deliverables**:
- Every answer includes proper source citation (Page + Section)
- Improved retrieval to support metadata filtering

**Success Criteria**:
- Source citation works reliably
- Users can verify answers by going to the mentioned page/section
- This becomes a core strength of the project

**Estimated Effort**: 1.5 – 2 weeks

---

### Phase 5: User Interface (Streamlit)
**Goal**: Make the system usable through a clean web interface.

**Key Features**:
- Upload PDF through UI
- Ask questions through UI
- Display answers with source citations
- Basic chat-like experience

**Deliverables**:
- Fully functional Streamlit web application
- Clean and usable interface

**Success Criteria**:
- Users can upload documents and ask questions without touching code
- Interface is intuitive and professional-looking

**Estimated Effort**: 2 – 2.5 weeks

---

### Phase 6: Polish, Testing & Documentation
**Goal**: Improve quality, fix issues, and document everything properly.

**Key Features**:
- Error handling and edge cases
- Better prompts and response formatting
- Project documentation (README + usage guide)
- Code cleanup and organization

**Deliverables**:
- Stable and reliable application
- Comprehensive README and documentation
- Tested with multiple financial documents

**Success Criteria**:
- Project is easy for others to understand and run
- Major bugs are fixed
- Code quality is good

**Estimated Effort**: 1.5 – 2 weeks

---

### Phase 7: Deployment (Optional but Recommended)
**Goal**: Make the application accessible online.

**Key Features**:
- Deploy the app on Streamlit Cloud or Render
- Make it publicly accessible (or with controlled access)

**Deliverables**:
- Live deployed version of LedgerMind
- Public link (for portfolio)

**Success Criteria**:
- Application is live and accessible
- Can be shared in portfolio and applications

**Estimated Effort**: 3 – 5 days

---

## 4. Summary of Phases

| Phase | Focus Area                    | Estimated Duration | Priority | Status    |
|-------|-------------------------------|--------------------|----------|-----------|
| 0     | Project Setup & Documentation | Done               | High     | Completed |
| 1     | Document Ingestion Pipeline   | 2 – 3 weeks        | High     | Pending   |
| 2     | Embeddings + Vector DB        | 1.5 – 2 weeks      | High     | Pending   |
| 3     | Basic RAG Pipeline            | 2 – 2.5 weeks      | High     | Pending   |
| 4     | Source Citation               | 1.5 – 2 weeks      | High     | Pending   |
| 5     | User Interface                | 2 – 2.5 weeks      | High     | Pending   |
| 6     | Polish & Documentation        | 1.5 – 2 weeks      | Medium   | Pending   |
| 7     | Deployment                    | 3 – 5 days         | Medium   | Pending   |

**Total Estimated Time**: 12 – 15 weeks (depending on consistency and learning curve)

## 5. Execution Approach
- Work phase by phase (do not start the next phase until the current one is reasonably complete)
- Document learnings and challenges in each phase
- Update GitHub README progressively
- Create content (YouTube/notes) alongside development if possible

## 6. Open Questions
- Should we add basic conversation memory in Phase 5 or later?
- Do we want to support multiple documents in one session from the beginning?
- When should we start creating content around this project?

---

**End of Roadmap Document**