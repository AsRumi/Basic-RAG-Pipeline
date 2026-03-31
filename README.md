<h1 align = "center"> RAG Pipeline, From Scratch </h1>

A complete Retrieval-Augmented Generation pipeline built from the ground up. Every component is hand-written and understood, no black-box framework abstractions.

---

## What is RAG?

Large language models have two fundamental knowledge limitations:

- **Staleness** - the model's knowledge is frozen at training time. Any data generated after that cutoff is invisible to it.
- **Specificity** - private, user-specific, or domain-specific data was never part of training to begin with.

The naive fix is to paste all relevant information directly into the prompt. This breaks down quickly due to latency costs, token cost scaling, and the **"lost in the middle" problem**, where models struggle to use information buried in the middle of a very long context window.

RAG solves this by retrieving only the most relevant pieces of information at query time and grounding the model's answer to that retrieved context.

---

## The Two Phases of RAG

**Indexing** is the offline preparation phase. Documents are chunked, embedded into vectors, and stored in a vector database. This happens once and is reused across all future queries. This also needs to happen everytime there is a change in documentation.

**Querying** is the online phase. When a user asks a question, the query is embedded using the same model, the most similar chunks are retrieved from the vector store, and those chunks are passed to an LLM alongside the original question to generate a grounded answer.

---

## Core Concepts

### Embeddings

An embedding is a function that maps text to a dense vector of numbers, typically hundreds of dimensions in size. This vector is produced by an **embedder** - a neural network trained to assign similar vectors to semantically similar pieces of text.

The higher the dimensionality of the vector, the more nuance it can capture.

> **Embeddings vs. Hashing** - Hashing maps text to a fixed identifier without caring about semantic meaning, which is fine for lookup tasks. Embeddings are different: two pieces of text with similar meaning must end up close together in vector space. Hashing cannot do this.

This project uses `all-MiniLM-L6-v2` from `sentence-transformers` as the embedding model.

### Vector Databases

Embeddings are stored in a **vector database** - a database optimized for similarity search rather than exact lookup. Instead of scanning all vectors at query time, vector stores use **ANN (Approximate Nearest Neighbor)** search, where similarity between vectors is precomputed at index time to avoid recalculating cosine similarity across the entire database on every query.

This project uses **ChromaDB** as the vector store.

### Chunking

An entire document cannot be embedded as a single vector, too much meaning is lost in the compression. Documents are split into smaller chunks: small enough to be precise, large enough to preserve context.

Chunks are overlapped at their boundaries so that information spanning two adjacent chunks is not lost. Three strategies exist for deciding where boundaries fall:

1. **Fixed-Size Chunking**: splits at a fixed character count, which can cut sentences mid-thought.
2. **Sentence-Aware Chunking**: splits only at sentence boundaries, preserving grammatical units.
3. **Recursive Chunking**: splits on a hierarchy of separators (paragraphs -> sentences -> words), falling back to finer splits only when necessary. This is the strategy used in this project, via LangChain's `RecursiveCharacterTextSplitter`.

### Retrieval

At query time, the query is embedded and the top-k most similar chunks are retrieved from the vector store using cosine similarity. Choosing k involves a tradeoff; too few chunks risks missing relevant context, too many introduces noise.

**Naive top-k retrieval has three failure modes:**

1. **Semantic gap**: the query and the answer use different vocabulary, so their embeddings are not as similar as they should be.
2. **Redundancy**: overlapping chunks can cause the same information to appear multiple times in the top-k results.
3. **Wrong chunk winning**: a chunk can score highly due to surface-level similarity without actually answering the question.

### Reranking

A **reranker** addresses these failure modes. It is a cross-encoder transformer trained to answer: _"Given this question, how well does this chunk answer it?"_ Unlike the bi-encoder used for retrieval (which embeds query and chunks independently), a cross-encoder sees the query and chunk together, allowing it to reason about their relationship with full attention.

The reranker is slower and cannot scale to millions of documents, so the pipeline combines both:

1. **Top-k retrieval (bi-encoder)**: fast, runs over the full index, returns a candidate set.
2. **Reranker (cross-encoder)**: slow, runs only over the candidate set, reorders by true relevance.

This project uses `cross-encoder/ms-marco-MiniLM-L-6-v2` for reranking.

### Generation and Grounding

The retrieved chunks are passed to an LLM alongside the user's query. The prompt has three parts, always in this order:

1. **System Instruction**: establishes the grounding rule: the model must answer only from the provided context, not from its training weights.
2. **Retrieved Context**: the reranked chunks injected into the prompt.
3. **User Query**: the original question.

Grounding solves three problems: it enforces **specificity** (the document knows more than general training data), **faithfulness** (the answer traces back to the source), and **staleness** (the document reflects the present, the model's weights do not).

If the retrieved context does not contain the answer, the model is instructed to say so rather than fabricate a response.

This project uses **Gemini 2.5 Flash-Lite** via the `google-genai` SDK for generation.

---

## When to Retrieve

Not every query needs retrieval. Four strategies exist for deciding when to invoke the retriever:

1. **Always retrieve**: simplest approach, retrieval happens on every query regardless of content.
2. **Query classification**: a separate model classifies the query and decides whether retrieval is needed.
3. **Retrieval confidence threshold**: retrieval is only used when the similarity score of the top result exceeds a minimum confidence value, otherwise the model falls back to its weights.
4. **Agentic RAG**: the most powerful and complex approach. Retrieval is provided as a tool to the LLM, which decides on its own when to call it, how many times, and with what sub-queries.

---

## Project Structure

```
rag-project/
├── document.txt          # Source document
├── embeddings.py             # Embed sentences, compute cosine similarity
├── vector_store.py           # ChromaDB setup
├── chunker.py                # Fixed-size and recursive chunking
├── ingest.py                 # Chunk -> embed -> store pipeline
├── retriever.py              # retrieve() and retrieve_and_rerank()
├── query.py                  # build_prompt(), ask(), interactive loop
└── requirements.txt
```

---

## Stack

| Component    | Tool                                         |
| ------------ | -------------------------------------------- |
| Embeddings   | `sentence-transformers` / `all-MiniLM-L6-v2` |
| Vector Store | ChromaDB (in-memory)                         |
| Chunking     | LangChain `RecursiveCharacterTextSplitter`   |
| Reranking    | `cross-encoder/ms-marco-MiniLM-L-6-v2`       |
| Generation   | Gemini 2.5 Flash-Lite (`google-genai`)       |

---

## Running the Pipeline

1. Clone the repo and activate your virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Add your Gemini API key to a `.env` file: `GEMINI_API_KEY=your_key_here`
4. Run ingestion to chunk, embed, and index the document:
   ```
   python ingest.py
   ```
5. Start the interactive query loop:
   ```
   python query.py
   ```

---
