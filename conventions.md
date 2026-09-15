# conventions.md — Self-Maintaining Vector Database (Design Record)

**Project:** Basic-RAG-Pipeline (branch `main`; v1 preserved at `v1-stable`)
**Last updated:** 2026-09-14
**Last commit:** `e4f827a Phase 4 done.` — v2 is feature-complete. The §24.1 closing work (evaluation set, `GUIDE.md`, README) is built and verified but not yet committed.

---

# START HERE

Read this section, then §25 and §26 (what Phase 4 does and how v2 was closed out), then §20 (how to talk to the user). Everything else is reference you can consult as needed. **The user wants this project finished quickly — do not re-derive settled decisions or re-run settled experiments.**

**v2 is feature-complete.** Nothing in §24.1 remains. Do not start anything in §24.3 without being asked.

## What this project is

A working RAG pipeline is being upgraded so the vector store **maintains itself**: when a newer document contradicts or duplicates something already stored, the older record is retired automatically. Nothing is ever deleted — records are tombstoned by flipping `status` to `superseded`, and the retriever filters on `status: "active"`.

## Where it stands: all four phases are done and verified. The store now maintains itself.

| Phase | What | State |
|---|---|---|
| 1 | Metadata, content-addressed ids, cosine space, `status` filter | **Done 2026-09-07** |
| 2 | Candidate nomination + append-only dry-run log | **Done 2026-09-08** |
| 3 | LLM adjudicator, logging only | **Done 2026-09-12** |
| 4 | Apply the verdicts — flip `status`, set `superseded_by` | **Done 2026-09-14 — see §25** |

What remains is in §24: the evaluation set, the learning guide, and a `README.md` that no longer describes v1.

## The live code

| File | Role |
|---|---|
| `store.py` | Embedding model, Chroma client, the collection. Guards that the space is cosine. |
| `llm.py` | Gemini client and `GEMINI_MODEL`. The model id lives here only. |
| `ingest.py` | Chunk, embed, write, with `--as-of`, `--dry-run`, `--no-adjudicate`, `--apply` |
| `supersede.py` | `nominate()`, `judge()`, `adjudicate()`, `apply()`, the log, and the report |
| `admin.py` | `--list`, `--stats`, `--rollback`, `--reapply`. The audit and undo surface. |
| `evaluate.py` | Scores `judge()` against `tests/contradictions.jsonl`. Exits non-zero on regression. |
| `retriever.py` | Vector search filtered to `status: "active"`, then cross-encoder re-rank |
| `query.py` | Prompt, Gemini call, REPL that prints sources |

`chunker.py`, `embeddings.py`, `vector_store.py` are **scratch files from the original learning exercise and are not on the live path.** Do not import them, do not fix them, do not treat `chunker.py`'s hand-written `chunk_text` as how chunking works.

## Exact state of the store right now

41 chunks, cosine space, **34 `active` and 7 `superseded`** — the Phase 4 verification run against the fixture has been applied and left in place.

| Source | Active | Superseded | `ingested_at` |
|---|---|---|---|
| `Aurora_Pro_1000_UserManual.txt` | 3 | 7 | 2025-01-15 |
| `Aurora_Pro_1000_UserManual-v2.txt` | 12 | 0 | 2026-09-14 |
| `Mongol Military.txt` | 13 | 0 | 2025-08-01 |
| `document.txt` | 6 | 0 | 2024-03-01 |

**The fixture is now ingested**, which is a change from every earlier phase. `supersession_log.jsonl` holds that applied run: 36 pairs, 33 nominated, 7 applied. To get back to the pre-Phase-4 store, either run `python admin.py --rollback` (which restores the 7 records but leaves the 12 v2 chunks in place) or rebuild from scratch as below.

## The test fixture and its known answers

`Aurora_Pro_1000_UserManual-v2.txt` is the manual with five deliberate edits. **These are the ground truth for evaluating any change to the adjudicator.** Re-run and re-score after touching the prompt, the floor, or `CANDIDATES_PER_CHUNK`.

| Edit | Correct verdict | Phase 3 result |
|---|---|---|
| "can be used while charging" → "cannot" | CONTRADICTS | correct |
| Pairing: 5s → 10s, Blue/Red → Green/Purple | CONTRADICTS | correct |
| "no harsh chemicals" → "isopropyl allowed if detached" | CONTRADICTS | got REFINES — **ambiguous case, not a bug, see §21.5** |
| Interference → "2.4GHz only, 5GHz fine" | **REFINES** | **correct — this is the trap case, it must keep passing** |
| New firmware section | INDEPENDENT | correct |

## Commands

```
python ingest.py --name FILE.txt --as-of YYYY-MM-DD      # real ingest, judges but changes nothing
python ingest.py --name FILE.txt --apply                 # ingest and retire what it replaces
python ingest.py --name FILE.txt --dry-run               # nominate + adjudicate, store nothing
python ingest.py --name FILE.txt --dry-run --no-adjudicate   # free, no model calls
python supersede.py                                      # report the log
python supersede.py --all                                # include pairs below the floor
python admin.py --stats                                  # counts by source and status
python admin.py --list                                   # what is retired and what replaced it
python admin.py --rollback [--since YYYY-MM-DD]          # undo, replaying the log backwards
python admin.py --reapply  [--since YYYY-MM-DD]          # redo, replaying the log forwards
python query.py                                          # interactive REPL
```

`--apply` is opt-in and off by default, and it refuses to run with `--dry-run`.

`supersession_log.jsonl` is **append-only**. Delete it before a fresh run or two runs will be interleaved in the report.

## Rebuilding the store from scratch

`chroma_db/` is gitignored and **never travels with the repo.** A fresh clone, or a move to another machine, starts with no store at all and nothing works until it is rebuilt.

Rebuild it with **exactly these dates.** They are not arbitrary: `ingested_at` decides which record is older, and the Phase 4 verification numbers in §23.7 only reproduce if these match.

```
Remove-Item -Recurse -Force chroma_db          # only if one already exists
python ingest.py --name document.txt --as-of 2024-03-01 --no-adjudicate
python ingest.py --name "Mongol Military.txt" --as-of 2025-08-01 --no-adjudicate
python ingest.py --name Aurora_Pro_1000_UserManual.txt --as-of 2025-01-15 --no-adjudicate
Remove-Item supersession_log.jsonl             # discard nomination noise from the rebuild
```

`--no-adjudicate` matters. Without it the second and third ingests pay for model calls to judge documents against each other, which is pure waste during a rebuild.

Afterwards the store must read **29 chunks, cosine space, all `active`**, split 6 / 13 / 10 across the three sources. If it does not, stop and find out why before building anything on top of it.

**Do not ingest `Aurora_Pro_1000_UserManual-v2.txt` during a rebuild.** It is the Phase 4 test fixture and must stay out of the store until `--apply` exists.

The chunk ids quoted in §23.7 also depend on `CHUNK_SIZE = 800` and `CHUNK_OVERLAP = 150`. Change either and those ids no longer exist.

## Traps that have already cost time — do not repeat them

1. **Sections 17 and parts of 18 are WRONG and were retracted.** §17 concluded chunk-boundary drift was harmless; §19 disproved that with real data. §18.3 said a 0.75 threshold was fine; it is not. **If §17, §18 and §19 appear to disagree, §19 wins.**
2. **Never gate nomination on an absolute similarity score.** A byte-identical chunk scores 1.0000 and a flat contradiction scores 0.9966. No cutoff separates them. Nomination takes the top N by rank with a low floor; the LLM decides. This is invariant #2 and it is backed by measurement (§18, §19).
3. **`nominate()` must run before `documents.upsert`.** That is what stops a batch being compared against itself (invariant #3). It is enforced by ordering, not by a filter — move it and the invariant breaks silently.
4. **Heredocs mangle backslash escapes.** Writing Python containing `\n` through a bash heredoc has corrupted this codebase twice. Build escapes with `chr(92)` or use the Write tool.
5. **The free-tier Gemini quota is per minute.** A burst of ~28 calls hits `429 RESOURCE_EXHAUSTED`. `judge()` already retries with backoff; keep that if you batch.
6. **Changing `CHUNK_SIZE` invalidates the whole store.** Stored chunks were split with the settings in force at ingest. Any change means re-ingesting everything.
7. **The byte-identical test on `DUPLICATE` is not a similarity threshold — do not "simplify" it into one.** A model-judged duplicate at 0.4483 tried to retire the warranty section because a table of contents listed it (§25.3). `DUPLICATE` acts only on exact text equality. `CONTRADICTS` is untouched by this and invariant #2 still stands.
8. **A rollback cannot be undone by re-running the ingest.** The chunks are already stored, so nothing is nominated and nothing can be applied. Use `python admin.py --reapply` (§25.5).

## What to do right now

Phase 4 is built, verified and applied — read **§25** for what it does and what it found. The remaining work is in **§24**: the evaluation set, the learning guide, and the `README.md` rewrite. **§23 is now a historical spec, and two of its numbers were wrong — §25.2 says which.**

---

## 1. How to work on this (process conventions)

- **Write to the user in plain prose. See §20.** This one matters as much as any technical convention here.
- **The user works discussion-first.** They explicitly asked for design conversation with *no code changes* until they say so. Do not start editing files because a design seems settled. Propose, then wait.
- **Do not treat this as a greenfield rewrite.** It is a working pipeline. Changes should be incremental, and each phase should leave the system in a working state.
- **Nothing is ever hard-deleted from the vector store.** This is the central safety principle of the whole feature (see §8).
- Ship the **audit trail before the automation**. Observability first, mutation last.

---

## 2. Repo state as it was at the START of this work (2026-09-07)

> **Historical. For the current state see START HERE at the top of this file.** This section describes the v1 pipeline before any of the supersession work, and is kept because the design critique in §4 refers to it. The code described here no longer exists in this form; it is preserved on the `v1-stable` branch.

Working, complete, basic RAG pipeline. Git branch `main`, clean tree. Latest commit at the time: `2290aca conventions.md creation`.

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

A 100-chunk document averaging 3 candidates each is **~300 LLM calls per ingest.** **Measured for real in §22** — the estimate held, but it only applies to a document's *first* ingest. Re-ingesting a revision costs far less, because unchanged chunks are skipped before nomination.

Mitigations:
- ~~Threshold aggressively so few pairs ever reach the LLM.~~ **Wrong, and dangerous. See §19 and §22.** Thresholding cannot separate a contradiction from a duplicate, and the pairs a high threshold discards are exactly the ones worth judging.
- Batch multiple candidate pairs into one call.
- Cache verdicts keyed on the **content-hash pair**, so re-ingests are free.
- `gemini-3.5-flash-lite` (already in use at `query.py:21`) is the right tier for this.

---

## 10. Implementation phases

| Phase | Content | Risk |
|---|---|---|
| **1** | Metadata + content-addressed ids + cosine space + `status` filter. No LLM, no automation. Everything is `active`; behaviour is unchanged. **Fixes the orphan bug on its own.** | Safe — **DONE 2026-09-07** |
| **2** | Candidate detection + dry-run log. Read-only. Lets the threshold be tuned against real output. | Safe — **DONE 2026-09-08** |
| **3** | LLM adjudicator, still logging only. | Safe — **DONE 2026-09-12** |
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

- Windows 11 Pro, PowerShell primary shell; Git Bash also available. **Run Python as `.venv/Scripts/python.exe`** rather than relying on an activated shell.
- Project root: `d:\Mutahar (I)\Basic RAG Pipeline`
  *(The path recorded before — `d:\VS Code\Python Codes\RAG Pipeline\Basic-RAG-Pipeline` — was a different machine. This repo moves between PCs, so treat any absolute path here as advisory.)*
- Virtualenv at `.venv` (Windows layout), interpreter at `.venv/Scripts/python.exe`.
- `GEMINI_API_KEY` is read from `.env` via `python-dotenv` in **`llm.py`**, which owns the Gemini client. `query.py` and `supersede.py` both import from it, so the model id and the key handling live in exactly one place.
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

---

## 21. Phase 3 implementation record (2026-09-12)

The LLM adjudicator, plus the nomination rework that §19 called for. **Still read-only: no `status` is ever changed.**

### 21.1 What was built

**`llm.py`** (new) holds the Gemini client and `GEMINI_MODEL`. `query.py` now imports from it instead of building its own client, so the model id lives in exactly one place.

**`supersede.py`** gained the adjudicator and lost the threshold:

- `CANDIDATES_PER_CHUNK = 3` and `SIMILARITY_FLOOR = 0.35` replace `SIMILARITY_THRESHOLD = 0.75`. Candidates are taken by rank; the floor only discards obvious noise.
- Byte-identical pairs are marked `DUPLICATE` in `nominate()` and never reach the model.
- `judge(earlier, later)` calls Gemini at `temperature = 0` with a `response_schema` pinning the verdict to the four allowed values, so parsing cannot drift.
- `by_age()` labels the passages EARLIER and LATER using `ingested_at`, never arrival order.
- `adjudicate(pairs)` fills `verdict` and `rationale` before the line is written, which keeps the log append-only.

**`ingest.py`** adjudicates by default; `--no-adjudicate` skips the model for cheap nomination-only runs.

### 21.2 Rate limiting is real and needed handling

The first full run died on `429 RESOURCE_EXHAUSTED` — 28 calls fired as fast as the loop could issue them, against a per-minute free-tier quota. `judge()` now retries up to four times with an 8, 16, 32 second backoff, and only for quota errors; everything else raises immediately. The rerun completed with no failures.

Anything that batches or parallelises adjudication later must keep this in mind. The §9 cost model counted calls but not their rate.

### 21.3 Nomination now finds what it was missing

All four edits with a real counterpart were nominated, including the interference refinement at **rank 2, similarity 0.4454** — the one the old 0.75 threshold discarded. Twelve chunks produced 36 pairs, 33 above the floor, of which 5 were settled free as exact duplicates. **28 model calls.**

### 21.4 Verdicts against the known answers

| Case | Expected | Got | |
|---|---|---|---|
| Negation: "can" → "cannot be used while charging" | CONTRADICTS | CONTRADICTS | pass |
| Values: pairing 5s → 10s, Blue/Red → Green/Purple | CONTRADICTS | CONTRADICTS | pass |
| Prohibition lifted: harsh chemicals → isopropyl allowed | CONTRADICTS | REFINES | see below |
| **Refinement trap: interference → 2.4GHz only** | **REFINES** | **REFINES** | **pass** |
| New section: firmware updates | INDEPENDENT | INDEPENDENT | pass |

The trap passing is the result that matters. Its rationale was correct and specific: the later text narrows the warning without making the earlier one wrong.

### 21.5 The isopropyl case is ambiguous, not a bug

Investigated rather than assumed. Adding an explicit rule that a general prohibition covers specific members of its category **did not change the verdict**. But rewriting the earlier passage to say "Do not use isopropyl alcohol" instead of "Do not use harsh chemicals" flipped it to `CONTRADICTS` immediately.

So the model reads the relationship correctly. It simply does not classify isopropyl alcohol as a harsh chemical — a judgment about the world, not about the text. The test case is weaker than intended because it requires that inference to be shared. The `createTimeSlots` example this edit was modelled on names *the same identifier* on both sides, which is why it is unambiguous and this is not.

**The prompt was left alone.** It passes the case that matters, the sharpened rule bought nothing, and tuning against one ambiguous example risks breaking the trap.

### 21.6 No false CONTRADICTS, and REFINES is over-applied in the safe direction

All four `CONTRADICTS` verdicts trace to the genuine charging reversal. Nothing was called a contradiction that was not one.

`REFINES` is applied loosely — several pairs that are really `INDEPENDENT` were called `REFINES` because one passage elaborates on a topic the other mentions. Both verdicts leave everything active, so the effect is nil. **Erring toward `REFINES` costs stale information surviving; erring toward `CONTRADICTS` destroys correct information. These are not comparable, and the observed bias is the right one.**

### 21.7 The adjudicator narrates chunk boundaries as if they were edits

Two rationales describe *packing* rather than authorship — "the later passage removes the troubleshooting section for frequent wireless disconnections", when in truth that text simply landed in a different chunk. Another said the later passage "prepends troubleshooting steps" to the warranty section, which is again just where the boundary fell.

Both produced harmless `REFINES` verdicts here. The risk is that a chunking artefact reads as deliberate removal and earns a `CONTRADICTS`. **Worth watching before Phase 4**, and another consequence of chunks not being semantically atomic.

### 21.8 One conflict produces several pairs, and only one gets quoted

The single charging reversal generated **four** `CONTRADICTS` pairs, because the note appears in overlapping chunks on both sides. Those four resolve to only **two distinct stored chunks**, so Phase 4 would not act four times.

Separately, when a chunk holds more than one conflict the rationale mentions only one of them. The chunk carrying both the charging note and the pairing steps was correctly marked `CONTRADICTS`, but its rationale cites only the charging sentence. The verdict and the resulting action are right; the audit trail is less complete than it looks. **If the log is to be trusted as a record of why something was retired, the adjudicator should be asked to list every conflict it finds, not just the decisive one.**

### 21.9 Collateral damage check: clean on this run

The two chunks Phase 4 would retire were tested line by line against v2. Every substantive line that would disappear is a line that was genuinely edited:

- one chunk loses only the charging note
- the other loses the charging note and the two pairing lines

Everything else in both chunks still appears verbatim in v2 and therefore survives inside the incoming chunks. **No correct information would have been lost.** This is the §12.5 trigger condition, and it has not fired — chunk-level identity is holding up so far, and claims stay deferred.

---

## 22. What adjudication actually costs (measured 2026-09-14)

Real numbers from the Phase 3 run on the twelve-chunk clone, not estimates.

### 22.1 The measurement

| | |
|---|---|
| Model calls | 28 |
| Input tokens, total | 15,589 |
| Input tokens per call | 557 |
| Output tokens, total | ~1,600 |
| Of which the fixed instruction block | **276 tokens per call, 49% of all input** |

For one document revision on `gemini-3.5-flash-lite` this is a rounding error. Check current pricing rather than trusting a figure written here.

### 22.2 Why it is cheaper than it looks: cost tracks *edits*, not document size

Because ids are content-addressed, a chunk whose text has not changed is already stored and is **skipped before nomination ever runs.** So re-ingesting a revision costs in proportion to how much changed.

Measured on the same file, chunked identically:

| Ingested as | New chunks | Pairs nominated |
|---|---|---|
| `Aurora_Pro_1000_UserManual-v2.txt` (new source) | 12 | 36 |
| `Aurora_Pro_1000_UserManual.txt` (a revision) | **7** | **21** |

On a 500-chunk manual with ten edited sections, a revision judges roughly fifteen chunks, not five hundred.

**The expensive case is a large document's first entry into a populated store**, where every chunk is new: roughly chunks × `CANDIDATES_PER_CHUNK`. Five hundred chunks would be around 1,500 calls.

### 22.3 Why this runs at ingest and never at query time

Supersession is a fact about the store, not an opinion about a question. Decide once at write time and every later query gets the benefit through a metadata filter that costs nothing. Adjudicating at query time would mean a model call on every question forever, latency on every answer, and a decision re-made — possibly differently — each time, with nothing recorded. Ingests are rare, queries are constant, so the expensive thinking belongs on the rare side. It is also what makes the audit trail possible: a supersession is a dated, reversible, inspectable fact.

### 22.4 Where the waste actually is

**Sixteen of the twenty-eight calls returned `INDEPENDENT`.** Over half the spend confirmed that unrelated things are unrelated.

But note *which* things. All 36 candidates came from the Aurora manual — **not one** came from `Mongol Military.txt` or `document.txt`, despite both sitting in the same collection. Vector search already filters across documents perfectly well on its own. The wasted calls are same-document comparisons: the specifications section against the packing list, which look alike because they share vocabulary and formatting.

**Do not try to fix this by raising the floor.** The verdict bands overlap:

| Verdict | Similarity range |
|---|---|
| `INDEPENDENT` | 0.3571 – 0.6129 |
| `REFINES` | 0.4454 – 0.9234 |
| `CONTRADICTS` | 0.5639 – 0.9970 |

A floor of 0.44 would save four calls and lose nothing — but only by a margin of 0.0004 against the interference edit at 0.4454. That is luck specific to this document, not a setting that generalises. At 0.45 real pairs start disappearing. This is the same lesson as §19, arriving from the cost side instead of the correctness side.

### 22.5 The optimisations that are actually safe

1. **Batch several pairs per call.** Half of every request is the same 276-token instruction block. Six pairs in one request sends it once instead of six times. Risk: cross-contamination between pairs in one context — verify against the §11 fixture before trusting it.
2. **Cache verdicts on the content-hash pair.** The same two passages never need judging twice. Makes repeat ingests free.
3. **Context caching** on the instruction block, if the API tier supports it.

None are built. All preserve correctness, which is the bar — lowering the standard of judgment is not on this list.

---

## 23. Phase 4 specification — BUILD THIS NEXT

The only phase that writes to the store. Everything needed to implement it is here.

### 23.1 What it does

Turn verdicts into state. For each adjudicated pair:

| Verdict | Action |
|---|---|
| `DUPLICATE` | the **older** record → `status: "superseded"` |
| `CONTRADICTS` | the **older** record → `status: "superseded"` |
| `REFINES` | nothing, both stay active |
| `INDEPENDENT` | nothing, both stay active |

Marking is metadata-only:

```python
documents.update(ids = [old_id],
                 metadatas = [{**old_metadata,
                               "status": "superseded",
                               "superseded_by": winning_new_id,
                               "superseded_at": time.time()}])
```

Embeddings and text are never touched. **Nothing is ever deleted.**

### 23.2 Ordering — this is the part that is easy to get wrong

```
chunk  ->  nominate  ->  adjudicate  ->  upsert  ->  apply  ->  log
                ^                          ^          ^         ^
                |                          |          |         |
    before the write, so a batch     new chunks   only now   records what
    cannot be compared with itself   must exist   can they   was actually
    (invariant #3)                   before a     be pointed  done
                                     pointer      at
                                     names them
```

`nominate()` must stay **before** the upsert and `apply()` must come **after** it, because `superseded_by` names a chunk that has to exist. `log()` moves to **last**, so each line records whether the mutation was actually applied. Today `log()` runs before the upsert — **that has to change.**

### 23.3 Guards, each of which is load-bearing

1. **Only supersede when `older == "old"`.** If the incoming chunk is the older one, superseding the stored record would let a backfilled old document clobber newer content. Log the verdict, apply nothing, and mark it for review. This is invariant #4.
2. **Deduplicate targets.** One real conflict produced **four** pairs in the Phase 3 run, resolving to two distinct stored chunks (§21.8). Group by `old_id` and act once.
3. **Pick a winner when several new chunks target the same old chunk.** Use the highest similarity. Record the choice.
4. **Skip records already superseded.** Applying twice must be a no-op.
5. **`--dry-run` must never apply.** Assert it.
6. **Never hard-delete.** Invariant #1.

### 23.4 CLI

Add `--apply`, **opt-in and off by default.** The user has said the end state is fully automatic but wants to verify updates by hand first (§12.6). Ship it opt-in, let them watch it work on the fixture, then flip the default once they say so.

### 23.5 Log schema additions

Add to each pair record: `applied` (bool), `applied_at` (float, `0` when not applied), and `skipped_reason` (str, `""` when applied — e.g. `"incoming chunk is older"`, `"target already superseded"`). Keep every existing field so old log lines stay readable.

### 23.6 Rollback — build it in the same pass, not later

§7.5 designates the log as the rollback path, and the feature is not safe to automate without one. Build `admin.py` (§7.6):

- `--list` — show superseded records with what replaced them and when
- `--rollback [--since TIMESTAMP]` — replay the log backwards, restoring `status: "active"`, `superseded_by: ""`, `superseded_at: 0.0`
- `--stats` — counts by source and status

### 23.7 Verification plan — exact expected numbers

> **Two numbers in this table are wrong and were corrected by the real run. See §25.2.** "Exactly 2 flipped" and "39 active" counted only the `CONTRADICTS` pairs and forgot that §23.1 makes `DUPLICATE` act too. The rest of the table held exactly.

Run against the fixture, which has known answers.

```
Remove-Item supersession_log.jsonl
python ingest.py --name Aurora_Pro_1000_UserManual-v2.txt --apply
```

Expected:

| Check | Expected |
|---|---|
| Store count | 29 → **41** (12 new chunks added) |
| Records flipped to `superseded` | **exactly 2** |
| Their ids | `Aurora_Pro_1000_UserManual.txt::acc646e8c513` and `::4d16f56ed232` |
| Active count afterwards | **39** |
| Superseded records still present via `documents.get()` | yes |
| Superseded records returned by `retrieve()` | **no** |

**The deliverable, in one line.** Before Phase 4, `python query.py` asked how long to hold the power button answers **"5 seconds"** — the stale value, because only v1 is stored. After Phase 4 it must answer **"10 seconds"**. That single behaviour change is the entire feature working end to end. Run it before and after and show the user both.

Then confirm `admin.py --rollback` returns the store to 41 records with 41 active, and that the query reverts to giving both answers.

### 23.8 Open decisions inside Phase 4 — settle these with the user, they are small

1. **Should `supersession_log.jsonl` be committed to git?** Currently ignored (§16.5). It is the rollback path, and a rollback path outside version control is one `git clean` from gone. **Decide before shipping `--apply`.**
2. **Same-source orphans (§14.5).** A chunk deleted in v2 lingers as `active` forever, because nothing walks the previous version to notice its absence. This is a *different* procedure from supersession — a set difference between two ingests of one source, needing no similarity search and no LLM. Either implement it or explicitly accept the gap.
3. **What to do when the incoming chunk is older.** Spec above says log and skip. Confirm that is what the user wants.

### 23.9 Known weaknesses to carry into Phase 4

- **The adjudicator narrates chunk boundaries as if they were edits** (§21.7). Two rationales described text landing in a different chunk as the later version "removing" a section. Harmless `REFINES` verdicts this time; a `CONTRADICTS` from the same confusion would retire good content. Watch for it in the applied log.
- **Rationales report only one conflict per pair** (§21.8). A chunk holding two conflicts gets the right verdict but an incomplete explanation. If the log is to justify what was retired, ask the adjudicator to list every conflict it finds.
- **Collateral damage has not fired yet** (§21.9). The two chunks Phase 4 would retire lose only lines the user genuinely edited. This is the §12.5 trigger for claim-level identity, and it remains unfired. Re-check it after every real apply.

---

## 24. What remains after Phase 4

Ordered by what the user gets for the effort.

### 24.1 Required to call the feature finished

1. ~~**Phase 4 + `admin.py` rollback** (§23).~~ **Done 2026-09-14, see §25.**
2. ~~**The evaluation set (§11).**~~ **Done 2026-09-14.** `tests/contradictions.jsonl` holds ten pairs, scored by `evaluate.py`. See §26.
3. ~~**The learning guide the user asked for.**~~ **Done 2026-09-14** — `GUIDE.md`. See §26.
4. ~~**Rewrite `README.md`.**~~ **Done 2026-09-14.** See §26.

### 24.2 Worth doing, not required

- **Batch adjudication and verdict caching** (§22.5). Only worth it if cost becomes real.
- **Delete or quarantine the scratch files.** `chunker.py`, `embeddings.py`, `vector_store.py` are learning exercises that actively mislead — `chunker.py`'s naive splitter caused a wrong conclusion in §17. Move them to `scratch/` or drop them; they are preserved in `v1-stable` either way.
- **The authority/confidence weight (§5, §4.6).** Parked deliberately, never cancelled. If it is revived, it **must be additive**, never multiplicative — re-rank scores are signed logits ranging roughly −11 to +11, and multiplying a negative score by an authority factor improves its rank (§4.4, confirmed in practice at §14.4).

### 24.3 Explicitly deferred — do not start these unprompted

- **Claim-level identity (§4.7, §12.5).** The theoretically correct unit, deliberately not built. Two independent arguments now support it: collateral damage, and nomination precision (§19). The trigger is collateral damage appearing in a real applied log. **It has not fired.** Do not build this without the user asking.
- **Re-chunking the corpus.** Any change to `CHUNK_SIZE` requires re-ingesting every document. Chunk size was also measured to be an unreliable lever (§19) — do not tune it hoping to improve nomination.

---

## 25. Phase 4 implementation record (2026-09-14)

The store writes for the first time. `--apply` turns verdicts into `status` changes and `admin.py` can undo them. Built to the §23 spec, with two corrections and one addition, all recorded below.

### 25.1 What was built

`supersede.py` gained `skip_reason()` and `apply()`. `skip_reason()` returns the single reason a pair cannot be acted on, or `""` if it can; `apply()` uses it to partition the pairs, groups the survivors by `old_id`, picks the highest-similarity winner per target, and calls `documents.update`. Every pair now also carries `applied`, `applied_at` and `skipped_reason`, defaulting to `False` / `0.0` / `"--apply not given"` so a log line always says why nothing happened.

`ingest.py` gained `--apply`, off by default and refused outright alongside `--dry-run`. The order is now `chunk -> nominate -> adjudicate -> upsert -> apply -> log`. `apply()` sits inside the `not args.dry_run` branch after the upsert, so a dry run cannot reach it even if the CLI guard were removed.

`admin.py` is new: `--list`, `--stats`, `--rollback`, `--reapply`, the last two sharing one `replay()` helper.

### 25.2 Two numbers in the §23.7 table were wrong

The spec expected **2** records flipped and **39** active. The real run flipped **7** and left **34**. The table counted only the `CONTRADICTS` pairs and overlooked that §23.1 makes `DUPLICATE` act too: five stored v1 chunks are byte-identical to incoming v2 chunks and were retired as duplicates, which is the deduplication half of the feature working as designed. Every other line of that table held exactly.

### 25.3 A model-judged `DUPLICATE` would have retired the warranty section

The Phase 3 log already contained the failure. At similarity **0.4483** the model called the v2 *table of contents* a duplicate of the v1 **warranty section**, reasoning that the contents page lists warranty as its final item. Applied literally, that retires the entire warranty text from retrieval because a contents page mentions the word.

**The rule now is that `DUPLICATE` only acts when `new_text == old_text` exactly.** A duplicate the model merely asserts is logged as `duplicate judged by model, not byte-identical` and left alone. `CONTRADICTS` is unaffected, because a contradiction is a claim about meaning that only the model can make; "nothing changed" is a claim about bytes that does not need it.

This is **not** a similarity threshold and does not touch invariant #2. It is an equality test on the text. Two pairs were blocked by it in the verification run: the table-of-contents case above, and the audio-presets chunk at 0.673 whose text shifted across a chunk boundary — that second one was probably a fair duplicate, and leaving it active is the cheap side of the error.

### 25.4 Verification results

Run as `python ingest.py --name Aurora_Pro_1000_UserManual-v2.txt --apply` against the 29-chunk store.

| Check | §23.7 expected | Actual |
|---|---|---|
| Store count | 29 -> 41 | **41** |
| Records flipped to `superseded` | 2 | **7** (5 byte-identical + 2 contradictions) |
| `::acc646e8c513` and `::4d16f56ed232` retired | yes | **yes** |
| Active afterwards | 39 | **34** |
| Superseded still returned by `documents.get()` | yes | **yes, with `superseded_by` and a timestamp on all 7** |
| Superseded returned by `retrieve()` | no | **no**, probed with six queries aimed straight at the retired text |
| Power button answer | 5s -> 10s | **"5 seconds" before, "10 seconds" after** |

Deduplication fired twice, exactly as §23.3 predicted: the two real contradictions each nominated their target from two different incoming chunks, and each target was retired once.

Applying twice is a no-op. Replaying all 36 logged pairs through `apply()` a second time changed nothing and reported `target already superseded` seven times.

### 25.5 Rollback alone leaves the store stranded, so `--reapply` was added

`admin.py --rollback` restored all 7 records and returned the store to 41 chunks, 41 active, with `query.py` once again giving both the 5-second and the 10-second answer.

**But the rollback could not be undone.** Re-running the ingest with `--apply` did nothing: content-addressed ids mean all 12 incoming chunks were already stored, so `new_chunks` was empty, nothing was nominated, and there was nothing left to act on. The only route back would have been deleting chunks and paying for a second adjudication. A rollback that cannot itself be reversed is its own trap, so `--reapply` replays the same log forwards, restoring `status`, `superseded_by`, and the **original** `applied_at` so the audit trail still records when the decision was made rather than when it was replayed. Both directions are idempotent.

This is an addition beyond the §23.6 spec. It is small and it costs no model calls, but it was not asked for.

### 25.6 Collateral damage: checked after the real apply, still clean

§24.3 makes collateral damage in an applied log the trigger for claim-level identity, so it was measured rather than assumed. For each retired chunk, every line longer than 25 characters was searched for across the whole active corpus:

| Retired chunk | Lines found nowhere in the active corpus |
|---|---|
| The five byte-identical duplicates | **0 each** |
| `::acc646e8c513` | 1 — "The headset can be used while charging" |
| `::4d16f56ed232` | 3 — the same charging line, "hold the Power Button for 5 seconds", "the Status LED will turn solid Blue" |

Every one of those is content the fixture's edits deliberately reversed. Nothing incidental was lost. **The trigger has still not fired** and claim-level identity remains deferred.

### 25.7 Verdicts drift slightly between runs at temperature 0

The Phase 3 run recorded 16 `INDEPENDENT` and 6 `REFINES`; this run recorded 15 and 7 on the same inputs. One pair moved. All five known-answer edits scored identically to Phase 3, including the interference trap case, which stayed `REFINES` at 0.4454 and was not applied.

Temperature 0 is not determinism. This is the argument for the evaluation set in §24.1 being written down properly: a one-pair drift is invisible today, and a drift that lands on a known answer would be invisible too.

### 25.8 What Phase 4 did not settle

- **Same-source orphans (§23.8 item 2) are an accepted gap**, decided by the user rather than overlooked. A chunk deleted in v2 still lingers as `active` forever. It needs a set difference between two ingests of one source — no similarity search, no model call — and it is not built.
- **The incoming-older path has never fired on real data.** All 36 pairs in both runs have the stored chunk as the older one. The guard was instead exercised directly: a synthetic backfill pair pointed at a real stored chunk applied nothing, reported `incoming chunk is older`, and left the record active. All nine `skip_reason()` branches were checked this way. The evaluation set in §24.1 should still include a genuine backfill document so the path runs end to end.
- **`supersession_log.jsonl` is now tracked in git**, removed from `.gitignore` by the user before this work. That settles §23.8 item 1 and §16.5: the rollback path is under version control.

---

## 26. Closing out v2: evaluation set, guide, README (2026-09-14)

The three items §24.1 listed after Phase 4. All are built; v2 is feature-complete.

### 26.1 The evaluation set

`tests/contradictions.jsonl`, ten pairs, run by `evaluate.py`. It calls `judge()` directly rather than going through nomination, so it tests the adjudicator prompt in isolation and touches neither the store nor the log. Exit code is non-zero if anything fails or errors.

All three cases §11 demanded are present: the `createTimeSlots` contradiction, the background-thread refinement built to look exactly like it, and the thread-safety negation pair. Five more are lifted verbatim from the real v1 -> v2 diff, as §11 asked — the hand-edits are the ground truth, so they were transcribed rather than re-derived. The last two are a reformatted-but-unchanged specifications block (the only `DUPLICATE` that has to reach the model, since byte comparison cannot catch it) and the packing-list-against-specifications pair that §22.4 identified as the archetypal wasted call.

**Current score: 9 pass, 1 known-wrong, 0 fail.**

The known-wrong is the isopropyl case, carried in the file as `"known": "REFINES"`. A case that always fails trains people to ignore failures, so it is recorded explicitly and reported separately from real regressions. If it ever starts answering `CONTRADICTS`, that shows up too, because the outcome stops matching either field.

Run this after touching the prompt, `SIMILARITY_FLOOR`, or `CANDIDATES_PER_CHUNK`. Note that it costs ten model calls and the per-minute quota applies; `judge()`'s backoff covers it.

### 26.2 The learning guide

`GUIDE.md`, twelve sections, written to be read start to finish rather than consulted. It is where the prose that §15 stripped out of the source files now lives.

It follows the reasoning in the order it actually happened, including the parts that were wrong: the age-multiplier proposal and why multiplying signed logits breaks, the 0.0034 measurement that killed thresholding, the 0.75 threshold that looked fine on a one-edit clone and dropped the two most important edits on the five-edit one, topic blending as the real cause rather than the boundary-position explanation first offered, and the table-of-contents verdict that produced the byte-identical guard. The corrections are left in deliberately — §19 correcting §17 and §18 is one of the more instructive things in this project's history, and a guide that presents the design as if it arrived fully formed would teach the wrong lesson.

It also explains why the byte-identical guard is not the thresholding mistake wearing a disguise: contradiction is a claim about meaning and needs the model, "nothing changed" is a claim about bytes and `==` is exact, free, and never hallucinates.

### 26.3 README

Rewritten. Both drift items from §2 are fixed: the stack table said "ChromaDB (in-memory)" against a `PersistentClient`, and the project structure block called the root `rag-project/` and omitted `chroma_db/`. A third error was found while rewriting — the generation section said **Gemini 2.5 Flash-Lite** while the stack table said 3.5 and `llm.py` says `gemini-3.5-flash-lite`. Now consistent.

The v1 teaching material is kept intact, since it is good and the "from scratch" framing still holds. Added: a section on keeping the store current, the four verdicts and what each does, the tombstone model, content-addressed ids, the audit trail, the full command set, and the evaluation instructions. The re-rank section now warns that the scores are signed logits, which is the §4.4 trap and the most expensive thing for a newcomer to get wrong.

`README.md` links `GUIDE.md`. Neither links this file, which is gitignored.

### 26.4 What is left

Nothing required. §24.2 and §24.3 stand as written: batching and verdict caching if cost ever becomes real, the scratch files still worth quarantining, the authority weight parked but not cancelled, and claim-level identity deferred until collateral damage actually appears in an applied log.
