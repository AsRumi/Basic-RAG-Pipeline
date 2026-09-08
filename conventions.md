# conventions.md — Self-Maintaining Vector Database (Design Record)

**Project:** Basic-RAG-Pipeline
**Date of this record:** 2026-09-07 (revised same day — all blocking decisions now resolved)
**Status:** **Phases 1 and 2 implemented and verified** ([§14](#14-phase-1-implementation-record), [§16](#16-phase-2-implementation-record-2026-09-08)). All blocking decisions answered ([§12](#12-decisions-resolved-2026-09-07)). Next up: Phase 3, the LLM adjudicator — still logging only. See §18 for the measurement that makes it mandatory. Code style is recorded in [§15](#15-code-style-in-this-repository).

This file exists so that a *new* Claude session (or a human) can pick up this exact problem with zero context loss. It captures the current repo state, the idea being pursued, the full design discussion including rejected approaches and the reasoning behind them, and the agreed implementation plan.

---

## 1. How to work on this (process conventions)

- **Write to the user in plain prose. See §20.** This one matters as much as any technical convention here.
- **The user works discussion-first.** They explicitly asked for design conversation with *no code changes* until they say so. Do not start editing files because a design seems settled. Propose, then wait.
- **Do not treat this as a greenfield rewrite.** It is a working pipeline. Changes should be incremental, and each phase should leave the system in a working state.
- **Nothing is ever hard-deleted from the vector store.** This is the central safety principle of the whole feature (see §8).
- Ship the **audit trail before the automation**. Observability first, mutation last.

---

## 2. Current repo state (verified 2026-09-07)

Working, complete, basic RAG pipeline. Git branch `main`, clean tree. Latest commit `2290aca conventions.md creation`.

**Branch plan:** the user is moving the current `main` to a `v1` branch and freeing `main` for the v2 work described in this document. So `v1` = the basic pipeline as documented in §2; `main` = the self-maintaining store being built.

### Live pipeline files (the actual code path)

| File | Role |
|---|---|
| `store.py` | **(new, Phase 1)** Owns the embedding model, the Chroma client and the collection. Everything else imports from here. |
| `ingest.py` | Reads a `.txt` file, chunks it, embeds it, writes it with metadata |
| `retriever.py` | Vector search (active-only) + cross-encoder re-rank |
| `query.py` | Prompt construction + Gemini generation + interactive REPL loop |

### Scratch / learning files (NOT part of the live path)

| File | Note |
|---|---|
| `chunker.py` | Early manual-chunking experiment. Has a module-level file read of `document.txt`. Unused by the pipeline. |
| `embeddings.py` | Cosine-similarity demo script. Unused by the pipeline. |
| `vector_store.py` | In-memory Chroma demo. Unused by the pipeline. |

Be careful not to confuse `vector_store.py` (scratch) with the real store, which currently lives inline in `ingest.py`.

### Known documentation drift (in `README.md`, not yet fixed)

- Stack table says **"ChromaDB (in-memory)"**; `ingest.py:12` uses `PersistentClient`.
- Project Structure block omits `chroma_db/` and still calls the root `rag-project/`.

Left alone deliberately — `README.md` describes the v1 pipeline and will need a rewrite once v2 lands anyway.

### Data / config

- `document.txt` (3.6 KB) and `Mongol Military.txt` (7.1 KB) — the two ingested corpora.
- `chroma_db/` — persisted Chroma store. Rebuilt on 2026-09-07 with **cosine** space and the full §6 metadata layer. Holds 29 chunks: 6 from `document.txt` (dated 2024-03-01), 13 from `Mongol Military.txt` (2025-08-01), 10 from `Aurora_Pro_1000_UserManual.txt` (2025-01-15). Gitignored, so it never travels with the repo — a fresh clone must re-ingest before anything works.
- `Aurora_Pro_1000_UserManual.txt` — the product manual from §12.3, the real test bed for supersession. Its edited clone is still to be written.
- `.env` — holds `GEMINI_API_KEY`.
- `.venv/` — local virtualenv (Windows layout, `.venv/Lib/site-packages`).
- `requirements.txt` — `langchain-text-splitters`, `sentence-transformers`, `chromadb`, `numpy`, `python-dotenv`, `google-genai`.

### Exact current behaviour (post Phase 1)

**`store.py`**
- `SentenceTransformer("all-MiniLM-L6-v2")` (384-dim), `chromadb.PersistentClient(path="chroma_db")`.
- Collection `"documents"` created with `configuration={"hnsw": {"space": "cosine"}}`.
- **Startup guard:** re-reads `documents.configuration["hnsw"]["space"]` and raises if it is not `cosine`. Load-bearing — see §14.2.

**`ingest.py`**
- Splitter: `RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)`.
- Ids are content-addressed: `f"{source}::{sha1(text)[:12]}"`, where `source` is `os.path.basename(--name)`. See §14.7.
- Writes the full §6 metadata block on every chunk.
- CLI: `--name` (default `document.txt`), `--as-of YYYY-MM-DD` (default: now).
- Within a batch, chunks that hash identically are collapsed, since Chroma rejects a repeated id in one call.
- Chunks whose id is **already stored are skipped entirely**, not re-upserted. Because the id *is* the content, a stored chunk holds byte-identical text; rewriting it would only serve to reset metadata that later phases have written. Re-ingest is therefore a true no-op.

**`retriever.py`**
- Imports from `store.py`, not from `ingest.py`. Importing the retriever no longer executes an ingest.
- `retrieve(query, k)` passes `where={"status": "active"}`.
- `retrieve_and_rerank(query, k)` over-fetches 10, re-ranks with `CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")`, and returns **dicts** — `{"id", "text", "metadata", "score"}` — rather than bare strings.

**`query.py`**
- `build_prompt` reads `result["text"]`; grounding instruction unchanged.
- `ask(query)` now returns **`(answer, results)`** so callers can cite sources.
- The REPL prints a `Sources:` block with each chunk's re-rank score, source file and id.

## 3. The idea being pursued (user's original framing)

Build a **vector database that maintains itself.**

Two motivating problems in large RAG databases:

1. **Versioned / contradictory information.** The user's canonical example:
   - Old: `"Do not call function 'createTimeSlots'"`
   - New: `"Call function 'createTimeSlots' after calling 'setTimeSlots'"`

   These are different and contradictory, but the second is the *newer* instruction and should supersede the first, because calls are now acceptable provided the stated condition is met. In a plain RAG pipeline both get retrieved and the model sees conflicting guidance.

2. **Duplicate / differently-credible information.** Two documents cover the same ground, but one source is more trustworthy and should take priority.

Nobody can be expected to manually delete stale documents every time a new one is added. So the database should:
- retire old information **based on time**, provided newer information on the same topic exists, and
- reconcile competing sources by **priority score**.

**User's proposed mechanism:** store an **age multiplier** alongside the embedding. Ingest with a timestamp; compute age from current time; among similar records the most recent gets the larger multiplier. Add a second, **user-supplied confidence multiplier** reflecting how useful/credible the ingester believes the document to be.

---

## 4. Design critique of the original proposal

All points below were raised and are considered settled reasoning. Do not re-litigate without new information.

### 4.1 It is two mechanisms, not one
Re-ranking is soft, reversible, and cheap to get wrong. Deletion is destructive and permanent. One multiplier cannot serve both — a 0.3-vs-0.9 gap is a fine reason to rank something lower and a terrible reason to delete it.
**Conclusion: multipliers govern ranking; supersession is a separate decision requiring separate, stronger evidence.**

### 4.2 Embeddings cannot detect contradiction (the load-bearing flaw)
- `"Do not call createTimeSlots"` vs `"Call createTimeSlots after setTimeSlots"` → high similarity under MiniLM (shared tokens). Correct clustering.
- But `"Do not call createTimeSlots"` vs `"Do not call createTimeSlots from a background thread"` → *also* high similarity, and that is a **refinement**, not a contradiction. Superseding the first would be wrong.
- Bi-encoders are notoriously **blind to negation**: `"X is thread-safe"` and `"X is not thread-safe"` embed almost identically.

**Conclusion: cosine similarity can only ever nominate *candidates for comparison*; it can never issue the *verdict*.** An adjudication step is mandatory — an NLI/entailment-style judgment classifying each pair. An LLM does this well, and Gemini is already wired up at `query.py:21`. Without this step the system will confidently delete correct information.

### 4.3 Recency is not truth
A *global* age multiplier decays everything, including stable foundational documents. A three-year-old but still-correct API contract would be outranked by a stray note from last week.
**Conclusion: decay must be scoped to a confirmed conflict cluster** — a document only competes on recency against records established to make a competing claim. Applied globally you have not built a self-maintaining database, you have built a "newest wins" database, which is strictly worse for non-operational corpora. (Recency is meaningless for `Mongol Military.txt`.)

### 4.4 The multiplier cannot live inside the vector search
Chroma's HNSW index returns top-k by vector distance alone; there is no hook to inject a metadata multiplier *into* the ANN search. Any weighting is necessarily a **re-ranking layer**: over-fetch (e.g. k=50), then score. Structurally this is the shape already present at `retriever.py:11-18`, and weighting belongs **after** the cross-encoder, not on raw cosine.

**Concrete trap:** `ms-marco-MiniLM-L-6-v2` emits **unbounded logits** (roughly −11 to +11). Multiplying a score of −8 by an authority factor of 2 makes it *worse*, while the same factor makes +8 *better*. Multiplication on signed scores is unstable.
**Prefer additive / log-linear:**

```
final = w1 * rerank_score + w2 * log(authority) - w3 * age_penalty
```

Tunable, no sign flips, no runaway products.

### 4.5 Tombstone, never delete
Add `status: active | superseded | deprecated` plus a `superseded_by` pointer. Chroma's `where` filter makes `{"status": "active"}` cheap at query time. Reversible, auditable, and it can answer "what was the rule before, and when did it change?" A threshold bug in a hard-delete system destroys data silently and permanently.

### 4.6 Human confidence scores do not compose
Every author rates their own document a 9. Per-document manual scores drift and become meaningless. **Derive authority from source tier instead** (official spec = 100, engineering wiki = 60, Slack thread = 20), with a per-document override as the exception. Consistent, and there is one place to retune it. *(Deferred — see §5.)*

### 4.7 Unit of identity
Superseding **chunks** means superseding arbitrary 300-character windows (`ingest.py:23`). "This chunk supersedes that chunk" is often incoherent, since a chunk is not a semantically atomic thing.

**What a "claim" would mean.** A chunk boundary is drawn by a character counter, which knows nothing about meaning. A *claim* is one atomic assertion extracted from the text. This chunk:

> "The scheduler runs every 60 seconds. Do not call createTimeSlots directly; it is invoked internally. Logging is disabled by default in production."

carries three unrelated facts. As claims:

1. The scheduler runs every 60 seconds.
2. `createTimeSlots` must not be called directly.
3. Logging is disabled by default in production.

If new content says *"Call createTimeSlots after setTimeSlots"*, it contradicts claim 2 **and only claim 2**. Superseding at chunk granularity retires the whole block, silently killing two correct facts as collateral damage. That is the real argument for claims — and it is the same argument that rules out *documents* as the unit, just at a smaller scale.

**Why it is not being built yet:** claims need an extraction LLM call per chunk *on top of* adjudication calls, and they force a two-level store — you retrieve **chunks** (a bare claim reads poorly in a prompt, stripped of its context) but version **claims**, so every claim needs a pointer to its parent chunk and a chunk is only fully dead once all its claims are superseded.

**Resolved: chunk, with chunk size raised. See §12.5.**

### 4.8 There is already a live staleness bug
`ingest.py:30` upserts IDs as `{filename}-{index}`. Re-ingest a document that got *shorter* and the orphaned high-index chunks from the previous version survive forever, with no metadata to detect them. This argues for a metadata layer regardless of the rest of the feature.

### 4.9 Prior art / naming
What is being described is, in database terms, **bitemporal, authority-weighted knowledge with automatic supersession**. Data warehousing solves the versioning half via slowly-changing dimensions (SCD Type 2). It is unsolved for vector stores specifically because embeddings destroy the information needed to detect contradiction.

---

## 5. AGREED SCOPE (current decision)

> **Focus on supersession only. The user-supplied confidence/authority weight is deferred.**

Rationale: the weight was only arithmetic on a score; supersession is the half that needs genuinely new machinery — identity, state, and a decision procedure.

Everything in §4.6, and the authority term in §4.4's formula, is **parked, not cancelled.**

---

## 6. Proposed metadata schema

Chroma metadata values must be `str` / `int` / `float` / `bool` — **no `None`, no lists.** Hence the `""` and `0` sentinels rather than nulls.

| field | type | purpose |
|---|---|---|
| `source` | str | which document the chunk came from |
| `ingested_at` | float | epoch seconds; drives "newer wins" |
| `status` | str | `"active"` / `"superseded"` |
| `superseded_by` | str | id of the winning chunk, `""` if none |
| `superseded_at` | float | epoch seconds, `0` if none |
| `content_hash` | str | exact-duplicate detection (incl. cross-source) |

---

## 7. Proposed code changes

### 7.1 Fix the IDs — they are positional today

Replace `f"{args.name}-{x}"` with content-addressed ids:

```
f"{source}::{sha1(chunk_text)[:12]}"
```

Benefits:
- Re-ingesting unchanged text becomes a genuine no-op (free exact dedup).
- Kills the orphan bug from §4.8.
- `superseded_by` pointers stay stable forever.

Why not a bare content hash with no `source` prefix: identical text from two different documents would silently collapse into one record, losing provenance. Keep `source` in the id and use the `content_hash` metadata field to detect cross-source duplicates explicitly.

**Why positional ids are actively dangerous:** `document.txt-4` can come to point at *different text* after a re-ingest, so any stored supersession pointer becomes silently wrong.

### 7.2 Two gotchas that must be handled

**(a) Distance metric.** `get_or_create_collection` defaults to `hnsw:space: "l2"`, and MiniLM vectors are not normalized by default. Current distances are therefore **not cosine**, and any threshold picked against them will not mean what it appears to mean. Need cosine set at collection creation. **This is fixed at creation time and cannot be changed later — it forces a rebuild of `chroma_db/`.**

*Implementation note (chromadb 1.5.5):* both `metadata={"hnsw:space": "cosine"}` and `configuration={"hnsw": {"space": "cosine"}}` work and produce an identical config. **`configuration=` is used**, because it is the current API and it does not pollute `collection.metadata` with a settings key. Verified default is `l2`.

**(b) Chunk overlap manufactures fake duplicates.** With `chunk_size=300, chunk_overlap=50`, adjacent chunks share 50 characters *by construction* and will look like near-duplicates.
- **Hard rule: never adjudicate two chunks from the same ingest batch against each other.**
- At 300 characters chunks are sentence fragments; supersession judgments on fragments will be noisy. **Decided: raise `chunk_size` to ~800–1000, keeping `chunk_overlap` proportional (~100–150).** A paragraph-sized chunk is far more semantically self-contained, which buys a good share of the claims benefit (§4.7) for zero extra machinery.

### 7.3 New module: `supersede.py`

Core pass. For each incoming chunk:

1. **Nominate** — query existing records with `status="active"`, excluding the current ingest batch, keeping only candidates above a similarity threshold.
2. **Adjudicate** — LLM call classifying the pair as one of:
   `DUPLICATE` / `CONTRADICTS` / `REFINES` / `INDEPENDENT`
3. **Apply** —

| verdict | action |
|---|---|
| `DUPLICATE` | older → superseded |
| `CONTRADICTS` | **older** → superseded |
| `REFINES` | both stay active |
| `INDEPENDENT` | both stay active |

"Older" means **earlier `ingested_at`, not later arrival order.** This matters so that backfilling an old document later cannot clobber newer content. Add an `--as-of` flag so a document's real date can override wall-clock time.

Marking uses `collection.update(ids=[old_id], metadatas=[...])` — metadata-only, embeddings untouched. **Nothing is ever deleted.**

### 7.4 Retrieval changes (`retriever.py`)

- Add `where={"status": "active"}` to the query at lines 22-23. **This is the payoff line** — one filter and superseded content stops reaching the model. Chroma applies `where` as a pre-filter, so `n_results` still returns that many active records.
- Stop discarding ids/metadata at line 17. Return tuples or dicts so provenance, citation, and "why did this surface?" debugging are possible.
- Fix the import direction: `retriever.py:5-6` importing from `ingest.py` means importing the retriever executes ingest's module-level code. Extract the Chroma client + embedding model into a small **`store.py`**. Small change, and this feature wants it anyway.

### 7.5 Audit trail (build this before the automation)

- Append-only **`supersession_log.jsonl`**: `{when, old_id, new_id, old_text, new_text, similarity, verdict, rationale}`.
- **`--dry-run`** flag on ingest that prints proposed supersessions without applying them.

This is the difference between a system you can trust and one that quietly eats your knowledge base. It is also the rollback path — replay the log backwards to restore `status`.

### 7.6 Optional: `admin.py`

List superseded records, un-supersede (rollback), print stats.

---

## 8. Non-negotiable invariants

1. **Never hard-delete.** Only flip `status` and set `superseded_by` / `superseded_at`.
2. **Similarity nominates; the LLM adjudicates.** Never supersede on a distance threshold alone.
3. **Never compare two chunks from the same ingest batch.**
4. **Order by `ingested_at`, never by arrival order.**
5. **Every mutation gets a log line.**

---

## 9. Cost model

A 100-chunk document averaging 3 candidates each is **~300 LLM calls per ingest.**

Mitigations:
- Threshold aggressively so few pairs ever reach the LLM.
- Batch multiple candidate pairs into one call.
- Cache verdicts keyed on the **content-hash pair**, so re-ingests are free.
- `gemini-3.5-flash-lite` (already in use at `query.py:21`) is the right tier for this.

---

## 10. Implementation phases

| Phase | Content | Risk |
|---|---|---|
| **1** | Metadata + content-addressed ids + cosine space + `status` filter. No LLM, no automation. Everything is `active`; behaviour is unchanged. **Fixes the orphan bug on its own.** | Safe — **DONE 2026-09-07** |
| **2** | Candidate detection + dry-run log. Read-only. Lets the threshold be tuned against real output. | Safe — **DONE 2026-09-08** |
| **3** | LLM adjudicator, still logging only. | Safe |
| **4** | Auto-apply. | **Only mutating phase** |

Phases 1–3 are reversible. By the time phase 4 runs, the log provides evidence that the verdicts are sane.

---

## 11. Evaluation

Write **ten hand-authored pairs with expected verdicts** in something like `tests/contradictions.jsonl`. Must include:
- The `createTimeSlots` contradiction from §3.
- A **refinement** case deliberately constructed to look like a contradiction (e.g. the background-thread example from §4.2).
- A negation pair (`"X is thread-safe"` / `"X is not thread-safe"`).

Ten pairs is enough to catch a broken adjudicator prompt. Without this, a regression in the adjudicator is invisible until it has already damaged the store.

**Source the pairs from the real diff.** Once the manual and its edited clone exist (§12.3), the edits made by hand *are* the ground truth — the user knows exactly which passages were changed into contradictions and which into refinements. Write those into `contradictions.jsonl` as the expected verdicts before running the adjudicator, not after.

---

## 12. Decisions (resolved 2026-09-07)

Every question that was blocking is now answered. Recorded with the reasoning so none of it gets re-litigated.

### 12.1 Rebuild `chroma_db/`? — **Moot, and free**

The store does not exist on this machine (§2). There is nothing to rebuild and no backfill script to write. Create the collection with `metadata={"hnsw:space": "cosine"}` on the very first ingest and the §7.2a trap never happens. This is the cheapest this decision will ever be — the setting is fixed at creation time and cannot be changed afterwards.

### 12.2 Which phase to start at? — **Phase 1**

Metadata + content-addressed ids + cosine space + `status` filter. No LLM, no automation. Externally observable behaviour is unchanged, and it fixes the orphan bug (§4.8) on its own merits.

### 12.3 Target corpus — **A product manual, hand-versioned**

`document.txt` and `Mongol Military.txt` are general knowledge, where recency implies nothing about correctness, and are the wrong test bed — acknowledged by the user.

Plan: download a real manual for some arbitrary product, ingest it, then clone the file and hand-edit the clone to plant deliberate contradictions **and** deliberate refinements, and ingest that as a second document. This is operational-instruction content, which is the corpus type the whole feature is designed around. The hand-edits double as evaluation ground truth (§11).

### 12.4 Simulating the time gap — **`--as-of`, never the wall clock**

Both ingests will happen minutes apart in real life, which would leave no meaningful recency signal. No simulation machinery is needed: `ingested_at` is a `float` that *we* write, and the wall clock is merely the default when nothing is specified.

```
python ingest.py --name manual_v1.txt --as-of 2024-03-01
python ingest.py --name manual_v2.txt --as-of 2025-08-01
```

The store now believes the two versions are 17 months apart.

This is **not** a test-only hack. Invariant #4 already requires ordering by `ingested_at` rather than arrival order, precisely so that backfilling a genuinely old document next month cannot clobber this month's content. The test scenario and the production requirement are the same mechanism, which is why `--as-of` earns its place in the real CLI.

**Test the reverse case too.** Ingest the edited clone with an *earlier* `--as-of` than the original. The system must **refuse** to supersede. If it supersedes anyway, arrival order has leaked into the comparison somewhere — that is a bug, and it is the single easiest invariant to break by accident.

### 12.5 Unit of identity — **Chunk, with chunk size raised. Claims deferred.**

Documents are ruled out: one document can legitimately produce several different verdicts against the store, and collapsing them to a single document-level verdict cannot represent that.

Claims (explained in §4.7) are the theoretically correct unit, but are **deliberately not being built now.** They cost an extraction LLM call per chunk on top of every adjudication call — a large, permanent API bill paid against a problem that has not actually surfaced yet.

Instead: stay at chunk granularity and raise `chunk_size` to ~800–1000 (§7.2b). Paragraph-sized chunks are far more semantically self-contained than 300-character fragments, which captures much of the claims benefit for none of the machinery.

**The trigger to revisit:** if the phase-2 dry-run log shows *collateral damage* — correct facts being retired because they happened to share a chunk with a stale one — that is the evidence that chunks are insufficient, and claims become a phase 5. Do not build them before that evidence exists.

### 12.6 Automation — **Fully automatic is the destination, not the starting point**

The user wants a fully automatic system, and that is the end state. For now it stays propose-and-verify so that database updates can be inspected by hand.

This does not change the phase plan in §10, it confirms it. Phases 2 and 3 are not optional detours around automation — they are how the similarity threshold gets tuned against real output from the actual manual, and how the adjudicator's verdicts are shown to be sane before anything is allowed to mutate. Turning phase 4 on against an untuned threshold is precisely the failure mode that quietly eats a knowledge base.

**Flip the switch when:** the dry-run log shows verdicts you agree with across a full ingest of the manual, and the §11 evaluation pairs pass.

---

## 13. Environment notes

- Windows 11 Pro, PowerShell primary shell; Git Bash also available.
- Project root: `d:\Mutahar (I)\Basic RAG Pipeline`
  *(The path recorded before — `d:\VS Code\Python Codes\RAG Pipeline\Basic-RAG-Pipeline` — was a different machine. This repo moves between PCs, so treat any absolute path here as advisory.)*
- Virtualenv at `.venv` (Windows layout), interpreter at `.venv/Scripts/python.exe`.
- `GEMINI_API_KEY` is read from `.env` via `python-dotenv` at `query.py:6-7`.
- Generation model in use: **`gemini-3.5-flash-lite`** — confirmed correct by the user. (`README.md` said "2.5"; corrected by the user on 2026-09-07.)

---

## 14. Phase 1 implementation record (2026-09-07)

Implemented, run and verified end to end. Files touched: `store.py` (new), `ingest.py`, `retriever.py`, `query.py`.

### 14.1 Verified behaviour

| Check | Result |
|---|---|
| Collection space | `cosine` |
| Metadata written | all six §6 fields on all 19 chunks |
| Re-ingest of an unchanged document | `0 new chunks, 6 already stored` — a true no-op |
| Chunk marked `superseded` | vanishes from `retrieve_and_rerank`, **remains in the store**, restored by flipping `status` back |
| `query.py` end to end | answers correctly and prints its sources |

### 14.2 The `hnsw:space` guard is load-bearing, not decorative

Tested directly against the old l2 store: `get_or_create_collection(..., configuration={"hnsw": {"space": "cosine"}})` **returned the existing l2 collection without any error or warning.** Asking for cosine and silently receiving l2 is precisely the failure that would make every tuned threshold in Phases 2–4 meaningless, with nothing visible to indicate why. Hence the explicit re-read and `RuntimeError` in `store.py`. **Do not remove it.**

### 14.3 Chunk size cut the corpus by two thirds

`Mongol Military.txt` went from **42 chunks at 300 chars to 13 at 800**. `document.txt` yields 6.

This lands directly on the §9 cost model, which was built on "100 chunks × ~3 candidates ≈ 300 LLM calls". Since adjudication cost scales with chunk count, paragraph-sized chunks make Phase 3 roughly **three times cheaper** than the estimate assumed — on top of producing better verdicts. §9's numbers are now conservative.

### 14.4 Re-rank scores confirmed unbounded

Observed in real runs: `+4.07`, `+2.05`, `+1.98`, `-0.18`, `-0.48`. Signed logits, exactly as §4.4 warned. **When the authority weighting in §5 is eventually un-parked, it must be additive.** Multiplying `-0.48` by an authority factor of 2 makes the chunk rank *better*, not worse.

### 14.5 Known gap: same-source orphans still linger

Content-addressed ids fix the *dangerous* half of §4.8 — an id can no longer come to point at different text, so supersession pointers stay sound. They do **not** fix the other half: a chunk deleted from v2 of a document remains in the store as `active` forever, because nothing walks the previous version to notice its absence.

Deliberately not fixed in Phase 1, for two reasons. It is a mutation, and Phase 1 is non-mutating by design. And sweeping same-source orphans is a *different* decision procedure from supersession — it is a set difference between two ingests of one source, needing no similarity search and no LLM at all.

Options when it is picked up: compare ids per source between ingests and mark the absentees `superseded_by="<removed in later ingest>"`, or leave it to the ordinary supersession pass and accept that genuinely deleted content lingers. **Open question, worth settling before Phase 4 auto-applies anything.**

### 14.6 Source names are normalised with `os.path.basename`

Found the hard way: the manual was first ingested as `.\Aurora_Pro_1000_UserManual.txt` (PowerShell tab-completion supplies the `.\`), and that prefix went straight into both the `source` metadata and every chunk id.

Left alone, ingesting the same file later as `Aurora_Pro_1000_UserManual.txt` would create a **second, unrelated source** holding identical text. The edited clone would then never be adjudicated against the original, and the whole supersession test would silently pass by doing nothing.

`ingest.py` now applies `os.path.basename` to `--name`, so how the path was typed cannot affect identity. The 10 malformed records were cleared and the manual re-ingested.

### 14.7 Not yet exercised

`--as-of` is implemented and its value is stored correctly (`document.txt` dated 2024-03-01, `Mongol Military.txt` 2025-08-01), but **nothing reads `ingested_at` yet** — no code compares two records by age until Phase 3. The reverse-order test in §12.4 cannot run until then.

---

## 15. Code style in this repository

The v1 codebase was deliberately spare: short module docstrings, almost no comments, names doing the explaining. Phase 1 was first written in a much heavier style and was cut back to match. **Match v1, not that first draft.**

### The rules

**Module docstring: one short line.** What the file is, nothing more. `query.py` has none and does not need one.

**No function docstrings.** If a function's purpose is not obvious from its name and body, the fix is usually a better name. Where genuine design reasoning exists, it belongs in this file — not in the source.

**Comments are rare, short, and answer *why*.** One line, placed on or above the line it concerns. A comment earns its place only when correct code would otherwise look arbitrary or wrong. The whole codebase currently carries three:

```python
# get_or_create hands back an existing collection unchanged, so a store built on
# another metric would be used silently. The metric cannot be altered in place.

source = os.path.basename(args.name) # ids must not depend on how the path was typed

where = {"status": "active"}) # superseded chunks stay stored, but must never reach the model
```

Each one records something the reader cannot deduce from the code. That is the bar.

**Never explain *what* the code does.** `# loop over the chunks` above a loop over the chunks is noise.

**No section banners, no ASCII dividers, no commented-out code, no TODO essays.**

**Formatting follows v1:** spaces around `=` in keyword arguments (`chunk_size = 800`), constants uppercase at module top, blank line between logical steps rather than comment headers.

### Where the reasoning goes instead

Stripping prose out of the source does not mean losing it. Design rationale goes in this file; the narrative walkthrough goes in the learning guide planned for the end of v2. The source stays readable at a glance, and the explanation stays somewhere it can be read in order.

**When adding code in later phases, write it at this density from the start.**

---

## 16. Phase 2 implementation record (2026-09-08)

Candidate detection and the dry-run log. **Read-only: no LLM, no mutation, no `status` ever changes.**

### 16.1 What was built

**`supersede.py`** (new)
- `nominate(chunks, source, ingested_at)` — one batched `documents.query` over `status="active"` records, `CANDIDATES_PER_CHUNK = 5`. Returns pair records; decides nothing.
- `log(pairs)` — appends to `supersession_log.jsonl`, one JSON object per line.
- `read_log()` / `preview()` — support for the report.
- Running `python supersede.py` prints the logged pairs sorted by similarity, with `--threshold` to re-evaluate at a different cutoff and `--all` to include pairs below it. It closes with a count at each of 0.9 → 0.5.

**`ingest.py`**
- `--dry-run`: nominates and logs, stores nothing.
- Nomination happens **before** the upsert.

**`.gitignore`** — `supersession_log.jsonl` added. See §16.5.

### 16.2 Invariant #3 is satisfied structurally, not by filtering

"Never compare two chunks from the same ingest batch" could have been enforced with an exclusion filter. It isn't. `nominate()` runs **before** `documents.upsert`, so at the moment of the query the batch is not in the store and cannot possibly be returned.

There is no threshold to misconfigure and no filter to forget. **If nomination is ever moved after the write, the invariant breaks silently** — chunks would be adjudicated against their own neighbours, which overlap by 150 characters by construction (§7.2b).

Only chunks that are genuinely new are nominated; ids already stored are skipped before nomination is reached.

### 16.3 Similarity is `1 - distance`

Chroma returns cosine **distance**. The pair records store similarity, so higher always means more alike. This is only correct because the collection is cosine space — on the l2 default the arithmetic would be meaningless, which is what the §14.2 guard protects.

### 16.4 First real numbers

Measured with a throwaway fixture: the manual's `SPECIFICATIONS` section with battery life edited from 35/20 hours to 45/28, plus a reworded troubleshooting line and a new firmware section. Dry-run only; the fixture and its log were deleted afterwards.

| Pair | Similarity |
|---|---|
| `SPECIFICATIONS` vs `SPECIFICATIONS` (battery numbers changed) | **0.956** |
| `SPECIFICATIONS` vs `PACKAGE CONTENTS` | 0.494 |
| everything else unrelated | 0.35 – 0.44 |

**The separation is much wider than expected.** A genuine near-duplicate scored 0.956 while the best unrelated pair reached 0.494 — an empty band of half the scale between them. The default `SIMILARITY_THRESHOLD = 0.75` sits in the middle of that gap.

Treat this as **one data point, not a tuned threshold.** It is a single edited section against a 10-chunk store, and the easiest possible case: a numeric change inside otherwise identical text. Retune against the real clone.

~~**Watch for chunk-boundary drift.**~~ **Retracted — measured and disproved. See §17.** The fixture's troubleshooting chunk scored 0.427 because the fixture was a short excerpt whose chunk held genuinely different content, not because boundaries had drifted.

### 16.5 Open: should the log be committed?

Currently gitignored — it is bulk generated text and, at Phase 2, pure diagnostics.

**This must be revisited before Phase 4.** §7.5 designates the log as the rollback path: replaying it backwards is what restores `status` after a bad supersession. A rollback path that is not under version control is one `git clean` away from being gone. Options are to commit it, or to accept that rollback is local-only and depends on the file surviving.

### 16.6 Not yet built

No adjudication. `verdict` and `rationale` are written as `null` on every pair so the log schema stays stable when Phase 3 fills them in. Nothing reads `older` yet either, though it is computed and stored from `ingested_at` per invariant #4.

---

## 17. Chunk-boundary drift: first dismissed, then found to be real (2026-09-08)

> **This section's original conclusion was wrong and is corrected in §19.** The experiments below were run on synthetic single-edit documents, which turned out to be far gentler than a real revision. Read §19 before acting on anything here.

§16.4 raised the worry that editing a document shifts every chunk boundary downstream, so corresponding sections in v1 and v2 would fail to align and real supersession candidates would score too low to be nominated. **That worry was wrong.** It was raised on one misread data point and is retracted.

### 17.1 What was measured

Four edit types applied to `Aurora_Pro_1000_UserManual.txt`, each chunked at 800/150 and compared by best-match cosine similarity of every v2 chunk against every v1 chunk.

| Edit | v1 → v2 chunks | byte-identical | min | median | below 0.75 |
|---|---|---|---|---|---|
| Mid-sentence insertion (not on a paragraph break) | 10 → 10 | 8 | 0.78 | 1.00 | **0** |
| Long block inserted early, forcing repacking | 10 → 12 | 10 | 0.04\* | 1.00 | 2\* |
| Early section deleted entirely | 10 → 9 | 9 | 1.00 | 1.00 | **0** |
| Every section renumbered | 10 → 10 | 0 | 0.99 | 1.00 | **0** |

\* The two low scores are the *inserted* text itself, which has no counterpart in v1 and is correctly unmatched. That is nomination working, not drift.

### 17.2 Why the worry was misplaced

`RecursiveCharacterTextSplitter` is **not** a fixed-window splitter. It tries `"\n\n"` first, then `"\n"`, then `" "`, and only falls back to raw character offsets when a single unbroken run exceeds `chunk_size`. Boundaries therefore land on paragraph breaks, which are stable features of the document — insert or delete a whole paragraph and the surrounding chunks are untouched. Nine of ten chunks came back byte-identical after a section was inserted.

Do not confuse this with `chunker.py`'s hand-written `chunk_text`, which *is* a naive fixed-window splitter. That function is scratch code and is not on the live path; the worry would have been correct for it.

### 17.3 Even genuine drift does not break nomination

Forced worst case: a single unbroken wall of prose with no paragraph breaks anywhere, ~90 characters inserted near the start, so every boundary shifts and **zero** chunks stay byte-identical.

```
best match per v2 chunk: 0.96 0.92 0.83 0.96 0.99 0.99 0.99 0.98 0.81
min 0.81 | median 0.96 | below 0.75: 0 of 9
```

Chunk size is what absorbs it. Shift an 800-character window by 90 characters and it still shares ~710 characters with its counterpart; the embedding is dominated by the bulk, not the edges. Adding paragraph breaks back to the same text restored 8 of 10 chunks to byte-identical.

Swept across chunk sizes 150–1600 on that same worst case, every configuration held a median near 0.96. Only `chunk_size=300` produced even one pair below 0.75. **No clean monotonic relationship** — where boundaries fall relative to the edit matters more than size — so this is weak supporting evidence for larger chunks, not proof.

### 17.4 A structure-aware splitter is not needed

Splitting on section-header regexes was tested against the character-based default. On the section-insertion case it moved the worst chunk from 0.91 to 0.96. Both are far above any usable threshold. **Not worth the complexity**, and it would only ever help documents with regular headers.

### 17.5 Where the real fragility is

Boundary drift is not a live risk. These are, and all are already on record:

- **Embeddings cannot tell contradiction from refinement** (§4.2). The load-bearing problem, and the entire reason Phase 3 exists.
- **Chunk-level collateral damage** (§4.7) — retiring a chunk kills every fact inside it, not just the stale one.
- **Same-source orphans** (§14.5) — content deleted in v2 lingers as `active`.

Nomination recall is a tunable, not a fragility: if pairs are being missed, raise `CANDIDATES_PER_CHUNK` or lower `SIMILARITY_THRESHOLD`. Both are cheap because nomination is pure vector search, and the LLM is the thing that actually decides. Widening nomination costs adjudication calls; it cannot cause a bad supersession on its own.

---

## 18. First real clone run — and the number that justifies the whole design (2026-09-08)

### 18.1 The first attempt reported a mistake in the inputs, not a bug

The first dry run of `Aurora_Pro_1000_UserManual-v2.txt` returned **ten pairs at exactly 1.000**. The cause: the clone was made first, then *the original was edited*. So `-v2.txt` held the unedited text and was byte-identical to what the store had ingested on 2025-01-15, while the edits sat in the file the store already knew.

The tool was correct. It said "this is a perfect copy of what I already have", which it was. Filenames were swapped so that `Aurora_Pro_1000_UserManual.txt` matches the store and `-v2.txt` carries the edits.

**Worth remembering:** an all-1.000 report means *nothing new was fed in*, not that supersession failed.

### 18.2 The result: a contradiction is indistinguishable from an exact duplicate

After the swap, v2's single edit is to the Bluetooth pairing steps:

```
-2. Press and hold the Power Button for 5 seconds until the Status LED flashes
-   alternating Blue and Red.
+2. Press and hold the Power Button for 10 seconds until the Status LED flashes
+   alternating Green and Purple.
-5. Once connected, the Status LED will turn solid Blue.
+5. Once connected, the Status LED will turn solid Green.
```

A flat operational contradiction — different hold time, different LED colours. Follow the old instructions and the device will not pair.

| Pair | Similarity |
|---|---|
| Nine byte-identical chunks | **1.0000** |
| The contradicting chunk | **0.9966** |

**The entire distance between "identical" and "actively wrong" is 0.0034.**

### 18.3 What this settles

§4.2 argued from first principles that embeddings cannot detect contradiction. This measures it on real data from the target corpus, and the margin is far tighter than the argument suggested.

- **No threshold can separate `DUPLICATE` from `CONTRADICTS`.** Any cutoff catching the contradiction at 0.9966 also catches every unchanged chunk at 1.0000. Any cutoff excluding duplicates excludes the contradiction. The two classes are not separable in this dimension **at all**.
- **Invariant #2 is not a design preference, it is a hard requirement.** Similarity nominates; the LLM decides. A distance-threshold implementation of this feature would be worse than doing nothing, because it would look like it was working.
- ~~**The 0.75 default threshold is fine.**~~ **Wrong — see §19.** This held only because the file contained a single edit. On the full five-edit clone, real supersession pairs landed as low as 0.4454.

### 18.4 Cheap win for Phase 3: settle exact duplicates without the LLM

Nine of ten nominated pairs were **byte-identical**. §6 already carries `content_hash` for exactly this. An identical hash *is* `DUPLICATE` by definition — no judgment required, no API call.

On this ingest that is **10 adjudication calls reduced to 1**. It also removes the largest and most boring category before the adjudicator ever sees it, so the prompt only ever faces pairs that genuinely differ. Fold this into Phase 3 before any prompt work.

### 18.5 The clone needs more edits before Phase 3 is properly tested

v2 currently contains **one** change, a clean contradiction. That exercises one verdict. Before the adjudicator can be trusted, the clone still needs the cases from §11 — above all a **refinement engineered to look like a contradiction**, since an adjudicator that returns `CONTRADICTS` for everything would score perfectly on the current file while being completely broken.

---

## 19. Nomination by threshold does not work (2026-09-08)

This section corrects §17 and part of §18. Both were written from experiments that were too gentle, and the full five-edit clone disproved them.

### What happened

The clone was finished with five edits: a contradiction in the pairing steps, a one-word negation of the charging note, a cleaning rule turned into a conditional permission, the interference warning narrowed to 2.4GHz, and a brand new firmware section. Running nomination against it, **four of the twelve incoming chunks scored below the 0.75 threshold**, and two of those four carried the edits that matter most.

The cleaning-rule change scored 0.6316 against its correct counterpart. The interference refinement scored 0.6298 against the wrong chunk entirely, with its correct counterpart sitting at rank two on 0.4454 — lower than plenty of pairs elsewhere in the run that were genuinely unrelated.

At a 0.75 threshold, neither would ever have reached the adjudicator. The two cases specifically designed to catch a broken adjudicator would have been silently dropped before it ever ran.

### Why it happens

§17 blamed boundary positions and concluded the recursive splitter was safe because it prefers paragraph breaks. That was the wrong mechanism.

The real cause is that **a chunk holding two unrelated topics gets an averaged embedding, and matches on whichever topic occupies more of it.** In the clone, the added text pushed the tail of the troubleshooting section into the same chunk as the whole warranty section. That chunk is mostly warranty text, so it matched the stored warranty chunk at 0.6298 while its actual counterpart — the troubleshooting chunk holding the old interference line — came second at 0.4454.

The same blending affects the stored side. The v1 troubleshooting chunk covers three separate problems, so even querying with the interference paragraph alone only reaches 0.4751 against it. Splitting the query into paragraphs was tested and does not fix this, because both sides are blends.

### What does not fix it

**Section-aware splitting** was tested with regex separators on section headers. It moved four sub-threshold chunks to three. Not a fix.

**Chunk size** is not a reliable lever. Sweeping 200 to 1200 characters, the worst-scoring edited chunk ranged from 0.49 to 0.96 with no monotonic trend — 800 happens to be a bad draw for this document and 1200 a good one. The variance comes from where boundaries land relative to the edits, which is not something that can be tuned in advance.

**Re-chunking the corpus** cannot fix it either, and is worth stating plainly: whatever is already stored was chunked with the settings in force at ingest time. Changing `CHUNK_SIZE` later does not re-chunk it. **Any change to chunking parameters requires re-ingesting every document, or comparisons are made between chunks built to different rules.**

### The fix: rank, with a floor, instead of a threshold

Stop using absolute similarity as a gate. For each incoming chunk, take the **top N candidates by rank regardless of score**, with a low floor of roughly 0.35 purely to skip obvious noise, and let the adjudicator decide. This is what invariant #2 always said — similarity nominates, the LLM adjudicates — and the threshold was quietly doing adjudication's job.

Two things make the extra calls affordable. Exact duplicates are settled by `content_hash` with no LLM call at all, which removed five of twelve chunks on this ingest. And the cost becomes predictable rather than data-dependent: (chunks − duplicates) × N. For this clone that is seven chunks × three candidates, so twenty-one calls.

Over-nominating costs money. Under-nominating loses information silently. Those are not comparable risks.

### The second independent argument for claims

§12.5 deferred claim-level identity and set the trigger as collateral damage showing up in the dry-run log. There is now a **separate** argument for it: chunk-level nomination cannot be made both complete and precise, because a chunk that mixes topics has an embedding that represents none of them well.

This does not reopen the decision. Rank-based nomination is the cheap fix and should be tried first. But if it proves insufficient, claims solve nomination and collateral damage at the same time, and that changes the cost-benefit.

---

## 20. How to talk to the user

This was asked for directly, and it applies to every reply in chat. It does not apply to this file, which is a reference document and is meant to be dense and cross-referenced.

**Write in complete sentences and ordinary prose.** Explain things the way you would to a colleague sitting next to you. The user is learning this material as it gets built, and prose that flows is what makes it stick.

**Do not cite section numbers at them.** Writing "per §4.2" or "this violates invariant #3" forces the reader to reconstruct a document in their head just to parse the sentence. Say the thing instead. Rather than "as established in §4.2", write "embeddings can't tell a contradiction from a rewording." The numbering exists so that a future session can navigate this file, not so that it can be quoted back at a person mid-conversation.

**Use tables only for real data.** A table of measurements, or a genuine side-by-side comparison, is useful. A table used to avoid writing paragraphs is not.

**Do not over-format.** Bold every third phrase and nothing reads as important. Headings on a four-sentence answer are noise.

**Lead with the answer.** If they ask whether something works, the first sentence says whether it works. Reasoning comes after, and detail after that.

**Be straight about mistakes.** Several conclusions in this file were wrong and had to be corrected by real data. Say so plainly in one sentence, correct it, and carry on. No apologising, no dwelling, and no burying the correction at the bottom of a long reply.
