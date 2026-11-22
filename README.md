# Margin – AI Knowledge Base

Margin is a small knowledge base application where you can upload documents and ask questions about their contents.

It supports PDF, DOCX, Markdown and TXT files. After uploading a document, the application extracts its content, splits it into sections, generates embeddings and stores everything in PostgreSQL.

You can then ask questions in plain English. Answers include citations pointing to the source document, page and section. The application also shows which passages were retrieved and how they were ranked.

The main focus of this project was experimenting with different RAG retrieval approaches and measuring how they affect answer quality.

## Tech Stack

- **Backend:** Python, FastAPI
- **Frontend:** Next.js 16
- **Database:** PostgreSQL 16 with pgvector
- **Embeddings:** BAAI/bge-small-en-v1.5
- **Embedding runtime:** ONNX through fastembed
- **Keyword search:** PostgreSQL full-text search with BM25 ranking
- **Reranking:** ms-marco-MiniLM-L-6-v2
- **LLM:** Groq or local Ollama
- **Deployment:** Docker Compose

The embedding model runs locally on CPU and uses around 350 MB of RAM. No GPU is required.

## Running the project

The easiest way to start everything is with Docker Compose.

```bash
docker compose up --build
```

Once the containers are running:

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API documentation: http://localhost:8000/docs

The application loads four sample documents on the first start:

- Employee handbook (PDF)
- Engineering guide (DOCX)
- Incident postmortem (Markdown)
- Product FAQ (TXT)

You can use these documents to try the search and question-answering features.

An LLM API key is not required to explore the application. Without one, you can still inspect retrieved passages and the retrieval trace.

To enable generated answers, create a free Groq API key and configure the backend:

```bash
cp backend/.env.example backend/.env
```

Set `LLM_API_KEY` in the environment file, then restart the application.

## How it works

There are two main parts: document ingestion and question answering.

### Document ingestion

When a document is uploaded, the backend:

1. Validates the file and checks its SHA-256 hash for duplicates.
2. Extracts text while preserving headings, pages and tables.
3. Removes repeated headers and footers.
4. Splits the content into chunks of up to 400 tokens, with around 60 tokens of overlap.
5. Generates embeddings using BGE-small.
6. Stores the chunks, metadata and embeddings in PostgreSQL.

Each chunk includes the document title and section name when generating its embedding. This helps preserve context when a passage is retrieved independently of the rest of the document.

### Question answering

When a user asks a question:

1. Follow-up questions are rewritten using the conversation history.
2. Vector search and keyword search run against PostgreSQL.
3. Their results are combined using Reciprocal Rank Fusion (RRF).
4. A cross-encoder can rerank the retrieved passages.
5. The selected passages are sent to the LLM.
6. The generated answer includes numbered citations.
7. A separate verification step checks whether each cited sentence is supported by its source passages.

The application supports four retrieval modes: vector, keyword, hybrid and hybrid with reranking.

## Retrieval experiments

I tested different retrieval approaches to see which worked better for different types of documents.

### BEIR SciFact

For a larger evaluation, I used the SciFact dataset from BEIR. It contains 5,183 scientific abstracts and 300 test queries with relevance labels.

The benchmark runs through the same ingestion and retrieval code used by the application.

| Retrieval method         |   nDCG@10 | Recall@10 | p50 latency |
| ------------------------ | --------: | --------: | ----------: |
| Vector search            |     0.712 |     0.826 |       29 ms |
| PostgreSQL ts_rank       |     0.390 |     0.536 |       45 ms |
| BM25                     |     0.696 |     0.818 |       97 ms |
| Hybrid with ts_rank      |     0.638 |     0.783 |       74 ms |
| Hybrid with BM25         | **0.724** | **0.853** |      136 ms |
| Hybrid + MiniLM reranker |     0.714 |     0.848 |       1.2 s |

The main finding was that PostgreSQL's default `ts_rank` was not working particularly well for this dataset. It does not account for inverse document frequency, so common terms can have too much influence on the ranking.

I implemented BM25 directly in SQL using the existing PostgreSQL full-text index. This improved keyword retrieval and made hybrid search the best-performing configuration in this benchmark.

The reranker was another interesting result. It slightly reduced retrieval quality on SciFact and increased latency significantly. It performed much better on the smaller company-document dataset described below.

### Tests with the sample documents

I also created a dataset of 40 questions based on the four documents included with the project.

Each question is labelled with the actual evidence text rather than a chunk ID, so the evaluation remains useful when chunking changes.

| Retrieval method   |    Hit@1 |    Hit@5 |   MRR@10 |
| ------------------ | -------: | -------: | -------: |
| Vector search      |     0.62 |     1.00 |     0.79 |
| BM25               |     0.85 |     1.00 |     0.91 |
| Hybrid             |     0.82 |     1.00 |     0.90 |
| Hybrid + reranking | **0.95** | **1.00** | **0.97** |

Reranking made the biggest difference for questions phrased differently from the original document text. Hit@1 for paraphrased questions improved from 0.79 to 0.96.

It also helped with shared keywords, but exact identifiers such as `INC-2047` remained harder.

This dataset is relatively small, so I use SciFact as the primary benchmark for comparing retrieval methods.

### Answer evaluation

I evaluated generated answers using `openai/gpt-oss-120b` through Groq and an LLM-based judge.

The test contained 40 answerable and 3 unanswerable questions.

| Metric                                   | Result |
| ---------------------------------------- | -----: |
| Correct answers                          |   1.00 |
| Faithfulness score                       |   1.00 |
| Answers with evidence in cited passages  |   1.00 |
| Correctly refused unanswerable questions |    3/3 |
| Sentences passing citation verification  |  39/40 |

One of the tests caught something worth mentioning.

When asked about on-call pay, the model said that the stipend was paid in addition to regular salary. The handbook never actually stated that. The answer passed the overall evaluation, but the sentence-level citation checker flagged it.

This is one reason I added a separate verification step rather than relying only on citations generated by the LLM.

## A few implementation details

### Hybrid retrieval

Vector search is useful when the question uses different wording from the source document. Keyword search is useful for exact terms, identifiers and names.

I wanted both approaches without introducing Elasticsearch or another search service.

The implementation uses:

- pgvector with HNSW for vector search.
- PostgreSQL `tsvector` and GIN indexes for keyword matching.
- BM25 scoring implemented in SQL.
- Reciprocal Rank Fusion to combine the two rankings.

BM25 uses term frequencies from the stored text positions, document frequencies from `ts_stat()`, and chunk lengths from the token counts. Term statistics are cached in a `term_stats` table and refreshed after ingestion.

### Reranking

The initial retrieval stages collect up to 20 candidates. The cross-encoder then scores the question and each passage together and reorders them.

I also tested reranking only the top 10 candidates. It gave the same accuracy on the sample dataset at roughly half the reranking cost.

### Citation verification

The answer is split into sentences, and each sentence is checked against the passages referenced by its citations.

The verifier looks for unsupported details, not just whether a citation exists.

For example, if the source says an account was locked for 14 minutes but the answer claims 2 hours, the checker flags the sentence and explains the mismatch.

This adds another LLM call and around 0.7 seconds to the response.

### Document processing

A few other things handled by the ingestion pipeline:

- PDF extraction using PyMuPDF.
- DOCX heading detection using paragraph styles.
- Tables preserved in document order.
- Duplicate detection using content hashes.
- Document processing states: pending, processing, ready and failed.
- Failed document processing can be retried.
- Interrupted jobs are re-queued after a server restart.
- Re-ingestion is idempotent.

## Running without Docker

Requirements:

- Python 3.11+
- Node.js 20+
- Docker (for PostgreSQL)

Run the following commands:

```bash
make setup
make db
```

Start the backend and frontend in separate terminals:

```bash
make api
```

```bash
make web
```

Other useful commands:

```bash
make test       # Run unit tests
make eval       # Run retrieval evaluation
make ablation   # Run ablation experiments
make gate       # Run the CI quality gate
make bench      # Run the BEIR SciFact benchmark
```

Answer evaluation can also be run with:

```bash
make eval-answers
```

This makes approximately 130 LLM calls, so it is paced to work with free-tier API limits.

## API endpoints

| Method | Endpoint                    | Description                |
| ------ | --------------------------- | -------------------------- |
| POST   | `/documents`                | Upload a document          |
| GET    | `/documents`                | List uploaded documents    |
| GET    | `/documents/{id}/chunks`    | Inspect document chunks    |
| POST   | `/documents/{id}/reprocess` | Reprocess a document       |
| DELETE | `/documents/{id}`           | Delete a document          |
| POST   | `/search`                   | Search documents           |
| POST   | `/ask`                      | Ask a question             |
| GET    | `/stats`                    | Get application statistics |

The search endpoint accepts a retrieval mode, so different search approaches can be compared without changing the application.

## Project structure

```text
backend/
  app/
    ingestion/
      extractors.py
      cleaner.py
      chunker.py
      pipeline.py
    retrieval/
      embedder.py
      search.py
      fusion.py
    generation/
      llm.py
      prompts.py
      rag.py
    api/
      documents.py
      query.py
    models.py
    schemas.py
    config.py
    main.py

  eval/
    dataset.jsonl
    run_eval.py
    results.md

  tests/

frontend/
sample_docs/
scripts/
docs/
```

## Current limitations

This is an MVP focused on RAG and retrieval experiments. There are a few things I would address before using it as a production service:

- **Authentication:** There is currently no user authentication or multi-tenant document isolation.
- **Background processing:** Ingestion runs through a single in-process worker thread. A proper task queue such as Celery, RQ or Arq would be more suitable for larger workloads.
- **Scanned PDFs:** OCR is not implemented.
- **BM25 updates:** Term statistics are recalculated after ingestion. This could be made incremental for larger collections.
- **Streaming:** Answers are currently returned without streaming.
- **Evaluation:** The sample dataset is small. Larger domain-specific datasets would help evaluate retrieval quality more reliably.

Some things I'd like to experiment with next are larger reranking models, ColBERT and parent-document retrieval.

## Repository

Source code: https://github.com/cantdoitbye/kms