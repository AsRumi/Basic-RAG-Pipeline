<h1 align = "center"> RAG Pipeline, From Scratch </h1>

A complete Retrieval-Augmented Generation pipeline built from the ground up, extended into a **vector store that maintains itself**. Every component is hand-written and understood, no black-box framework abstractions.

When a newer document contradicts or duplicates something already stored, the older record is retired automatically. Nothing is ever deleted — records are tombstoned, and the retriever only ever sees the active ones.

> **v1**, the basic pipeline without supersession, is preserved on the `v1-stable` branch. `git checkout v1-stable` for that version.
>
> **[GUIDE.md](GUIDE.md)** is a narrative walkthrough of everything v2 changed and why, including the measurements behind each decision and the two conclusions that turned out to be wrong. Read that if you want the reasoning rather than the reference.

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

This project uses **ChromaDB**, persisted to disk in `chroma_db/`. The collection is explicitly configured for **cosine** space, and startup fails loudly if an existing store was built on a different metric — the metric cannot be changed in place, and a store on the wrong one would otherwise be used silently.

### Chunking

An entire document cannot be embedded as a single vector, too much meaning is lost in the compression. Documents are split into smaller chunks: small enough to be precise, large enough to preserve context.

Chunks are overlapped at their boundaries so that information spanning two adjacent chunks is not lost. Three strategies exist for deciding where boundaries fall:

1. **Fixed-Size Chunking**: splits at a fixed character count, which can cut sentences mid-thought.
2. **Sentence-Aware Chunking**: splits only at sentence boundaries, preserving grammatical units.
3. **Recursive Chunking**: splits on a hierarchy of separators (paragraphs -> sentences -> words), falling back to finer splits only when necessary. This is the strategy used in this project, via LangChain's `RecursiveCharacterTextSplitter`.

Chunks are 800 characters with 150 characters of overlap. **Changing either value invalidates the entire store**, because stored chunks were split with whatever settings were in force when they were ingested; a change means re-ingesting everything.

### Retrieval

At query time, the query is embedded and the top-k most similar chunks are retrieved from the vector store using cosine similarity. Choosing k involves a tradeoff; too few chunks risks missing relevant context, too many introduces noise.

**Naive top-k retrieval has three failure modes:**

1. **Semantic gap**: the query and the answer use different vocabulary, so their embeddings are not as similar as they should be.
2. **Redundancy**: overlapping chunks can cause the same information to appear multiple times in the top-k results.
3. **Wrong chunk winning**: a chunk can score highly due to surface-level similarity without actually answering the question.

Retrieval is filtered to `status: "active"`, so superseded records remain in the store but can never reach the model.

### Reranking

A **reranker** addresses these failure modes. It is a cross-encoder transformer trained to answer: _"Given this question, how well does this chunk answer it?"_ Unlike the bi-encoder used for retrieval (which embeds query and chunks independently), a cross-encoder sees the query and chunk together, allowing it to reason about their relationship with full attention.

The reranker is slower and cannot scale to millions of documents, so the pipeline combines both:

1. **Top-k retrieval (bi-encoder)**: fast, runs over the full index, returns a candidate set.
2. **Reranker (cross-encoder)**: slow, runs only over the candidate set, reorders by true relevance.

This project uses `cross-encoder/ms-marco-MiniLM-L-6-v2` for reranking. Note that its scores are **signed logits** ranging roughly −11 to +11, not normalised scores — anything that weights them must be additive, since multiplying a negative score by a factor below 1 *improves* its rank.

### Generation and Grounding

The retrieved chunks are passed to an LLM alongside the user's query. The prompt has three parts, always in this order:

1. **System Instruction**: establishes the grounding rule: the model must answer only from the provided context, not from its training weights.
2. **Retrieved Context**: the reranked chunks injected into the prompt.
3. **User Query**: the original question.

Grounding solves three problems: it enforces **specificity** (the document knows more than general training data), **faithfulness** (the answer traces back to the source), and **staleness** (the document reflects the present, the model's weights do not).

If the retrieved context does not contain the answer, the model is instructed to say so rather than fabricate a response.

This project uses **Gemini 3.5 Flash-Lite** via the `google-genai` SDK for generation.

---

## When to Retrieve

Not every query needs retrieval. Four strategies exist for deciding when to invoke the retriever:

1. **Always retrieve**: simplest approach, retrieval happens on every query regardless of content.
2. **Query classification**: a separate model classifies the query and decides whether retrieval is needed.
3. **Retrieval confidence threshold**: retrieval is only used when the similarity score of the top result exceeds a minimum confidence value, otherwise the model falls back to its weights.
4. **Agentic RAG**: the most powerful and complex approach. Retrieval is provided as a tool to the LLM, which decides on its own when to call it, how many times, and with what sub-queries.

---

## Keeping the Store Current

Grounding fixes staleness only if the store itself is current. It usually is not. Ingest a revised manual and you now hold both versions; both score highly against the same questions, both get retrieved, and the model receives instructions that contradict each other.

### Similarity nominates, a model adjudicates

The tempting fix is to treat a high similarity score as evidence of duplication. Measured on this project's own corpus, that does not work at all:

| Pair | Cosine similarity |
|---|---|
| Byte-identical chunks | 1.0000 |
| A chunk edited into a flat contradiction | 0.9966 |

The gap between "nothing changed" and "actively wrong" is **0.0034**. No threshold separates them, and the same blindness applies to negation — "X is thread-safe" and "X is not thread-safe" embed almost identically.

So the work splits in two. Cosine similarity answers *are these about the same thing?*, which it does well, and nominates the top three candidates per incoming chunk by rank. A language model then answers *do they disagree?*, returning one of four verdicts under a JSON schema:

| Verdict | Meaning | Effect |
| --- | --- | --- |
| `DUPLICATE` | The later passage says the same thing | Older record retired, **only if the text matches exactly** |
| `CONTRADICTS` | They cannot both be true or both be followed | Older record retired |
| `REFINES` | The earlier passage is still true, the later is more precise | Both stay active |
| `INDEPENDENT` | Different subjects | Both stay active |

Byte-identical text never reaches the model — it is settled for free by comparing content hashes.

### The tombstone model

A retired record keeps its text and its embedding. Three metadata fields change: `status` becomes `superseded`, `superseded_by` records the id of the chunk that replaced it, and `superseded_at` records when. **Nothing is ever deleted.** An automated system retiring knowledge on a model's judgment will sometimes be wrong, and the whole design rests on that being recoverable.

Chunk ids are **content-addressed** — the source filename plus a hash of the chunk text — rather than positional. An id names a specific piece of text permanently, and re-ingesting a document skips every chunk that did not change, so cost tracks edits rather than document size.

### The audit trail

Every pair ever considered is appended to `supersession_log.jsonl`: both passages, the similarity, the verdict, the model's quoted reasoning, whether it was applied, and if not, why not. The log is also the rollback path, which is why it is tracked in git rather than ignored.

`--apply` is opt-in and off by default. Run an ingest without it to see what *would* happen before anything changes.

---

## Project Structure

```
Basic-RAG-Pipeline/
├── store.py                  # Embedding model, Chroma client, collection. Guards cosine space.
├── llm.py                    # Shared Gemini client and model id
├── ingest.py                 # Chunk -> embed -> store, with --as-of, --dry-run, --apply
├── supersede.py              # nominate(), judge(), adjudicate(), apply(), the log and its report
├── retriever.py              # retrieve() filtered to active, and retrieve_and_rerank()
├── query.py                  # build_prompt(), ask(), interactive loop
├── admin.py                  # --list, --stats, --rollback, --reapply
├── evaluate.py               # Scores the adjudicator against known-answer pairs
├── tests/
│   └── contradictions.jsonl  # Ten hand-authored pairs with expected verdicts
├── chroma_db/                # Persistent vector store (gitignored, rebuilt by ingesting)
├── supersession_log.jsonl    # Append-only audit trail and rollback path
├── GUIDE.md                  # Narrative walkthrough of the v2 design
└── requirements.txt
```

`chunker.py`, `embeddings.py` and `vector_store.py` are scratch files from the original learning exercise and are **not** on the live path.

---

## Stack

| Component    | Tool                                         |
| ------------ | -------------------------------------------- |
| Embeddings   | `sentence-transformers` / `all-MiniLM-L6-v2` |
| Vector Store | ChromaDB (persistent, cosine space)          |
| Chunking     | LangChain `RecursiveCharacterTextSplitter`   |
| Reranking    | `cross-encoder/ms-marco-MiniLM-L-6-v2`       |
| Generation   | Gemini 3.5 Flash-Lite (`google-genai`)       |
| Adjudication | Gemini 3.5 Flash-Lite, JSON schema, temp 0   |

---

## Running the Pipeline

1. Clone the repo and activate your virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Add your Gemini API key to a `.env` file: `GEMINI_API_KEY=your_key_here`

`chroma_db/` is gitignored and never travels with the repo, so a fresh clone starts with no store. Build one by ingesting:

```
python ingest.py --name document.txt --as-of 2024-03-01 --no-adjudicate
```

`--as-of` sets the date the content is from, which is what decides who is older when two records conflict. It defaults to now. `--no-adjudicate` skips the model calls, which is what you want while populating an empty store.

Then ask it something:

```
python query.py
```

### Ingesting a revision

```
python ingest.py --name manual-v2.txt --dry-run       # judge, store nothing
python ingest.py --name manual-v2.txt                 # store, judge, change nothing
python ingest.py --name manual-v2.txt --apply         # store, judge, retire what it replaces
```

`--apply` refuses to run alongside `--dry-run`.

### Inspecting and undoing

```
python supersede.py                    # report the log
python supersede.py --all              # include pairs below the similarity floor
python admin.py --stats                # counts by source and status
python admin.py --list                 # what is retired and what replaced it
python admin.py --rollback             # replay the log backwards, restoring records
python admin.py --reapply              # replay it forwards again
```

Both `--rollback` and `--reapply` accept `--since YYYY-MM-DD` and are idempotent. A rollback cannot be undone by re-running the ingest — the chunks are already stored, so nothing gets nominated — which is why `--reapply` exists.

### Evaluation

```
python evaluate.py
python evaluate.py --verbose
```

Scores the adjudicator against ten hand-authored pairs in `tests/contradictions.jsonl` with known correct verdicts, including a refinement deliberately built to look like a contradiction and a negation pair. Exits non-zero on any regression. One case is recorded as a known wrong answer so that it cannot mask a real one.

Run this after any change to the adjudicator prompt, the similarity floor, or the number of candidates per chunk.
