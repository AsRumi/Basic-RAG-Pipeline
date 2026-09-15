# How the store learned to maintain itself

This is a walkthrough of everything version 2 changed and why, meant to be read in order rather than consulted. It assumes you know what the v1 pipeline does: chunk a document, embed the chunks, store them, retrieve the nearest ones at query time, re-rank them, and hand them to a model. If that part is unfamiliar, read the README first.

Nearly every design decision here was argued about, and several were wrong the first time and had to be corrected by measurement. The corrections are the interesting part, so they are left in.

---

## 1. The problem: a store that quietly rots

A RAG store is usually described as a knowledge base. It behaves more like a filing cabinet that nobody ever cleans out.

Suppose your internal documentation says, in a page written two years ago:

> Do not call function `createTimeSlots`.

And then, last month, somebody writes a newer page:

> Call `createTimeSlots` after calling `setTimeSlots`.

Both pages get chunked, embedded and stored. Both are about the same function, so both score highly against a question about it, and both get retrieved. The model now receives two instructions that cannot both be followed and produces something confident and wrong, or hedges and gives you both. Nothing in the pipeline noticed, because nothing in the pipeline is looking.

You can fix this by hand in a store of thirty chunks. You cannot fix it by hand in a store of thirty thousand, and the moment you stop fixing it by hand the store begins to decay. So the question version 2 set out to answer is: **can the store notice for itself that something it holds has been superseded, and retire it?**

---

## 2. The first instinct, and the three things wrong with it

The obvious mechanism is to make recency win. Store a timestamp with every chunk, compute an age multiplier, and let newer records outrank older ones during retrieval. Add a second multiplier for how much you trust the source, so an official manual beats a forum post.

It is a reasonable first idea and it does not survive contact with the details.

**Recency is not truth.** A newer document is not automatically correct. It might be a draft, a partial note, or a backfill of something historical. Time is evidence about which of two statements is current; it is not evidence about which is right. The system can use it to decide *which record loses* once a conflict is established, but it cannot use it to establish that a conflict exists.

**The multiplier cannot live inside the search.** This one is a genuine trap. The re-ranker is a cross-encoder, and its outputs are signed logits running from roughly −11 to +11, not scores in a nice zero-to-one range. If you multiply a chunk's score by an authority factor of 1.5, a good chunk at +6 becomes +9 and rises, but a bad chunk at −8 becomes −12 and falls further, while a bad chunk at −8 multiplied by an authority factor of *0.5* becomes −4 and **rises**. Penalising a low-authority document would promote it. Any weighting of this kind has to be additive, and the whole idea was parked rather than built.

**And the load-bearing flaw: embeddings cannot see contradiction at all.** This is the one that reshaped the design, so it gets its own section.

---

## 3. Why similarity can nominate but never decide

Embeddings put semantically similar text close together. The intuition people carry into this is that a contradiction ought to be far away — it says the opposite, after all.

It is not. Consider these two:

> Do not call `createTimeSlots`.

> Call `createTimeSlots` after calling `setTimeSlots`.

High similarity. They share almost every token. Good — we want them compared.

Now these two:

> Do not call `createTimeSlots`.

> Do not call `createTimeSlots` from a background thread.

*Also* high similarity, and for the same reason. But this is a refinement. The rule still holds; it has only been narrowed. Retiring the first because the second exists would delete a true statement.

And bi-encoders are famously blind to negation. "X is thread-safe" and "X is not thread-safe" embed almost identically, because one token flipped in a sentence of ten barely moves the vector.

This was argued from first principles first, and then measured on the real corpus, and the measurement was worse than the argument. A product manual was cloned and edited to plant a flat contradiction — the pairing instructions changed from a five-second hold with a blue-and-red flash to a ten-second hold with green-and-purple. Following the old version, the device does not pair. Then both versions were embedded and compared:

| Pair | Cosine similarity |
|---|---|
| Byte-identical chunks | 1.0000 |
| The contradicting chunk | 0.9966 |

**The entire distance between "nothing changed" and "actively wrong" is 0.0034.**

There is no threshold in that gap. Any cutoff that catches the contradiction also catches every unchanged chunk in the document; any cutoff that excludes duplicates excludes the contradiction too. The two classes are not separable in this dimension — not poorly separable, *not separable*.

So the architecture splits in two, and this is the single most important idea in version 2:

> **Similarity nominates candidates for comparison. A language model issues the verdict.**

Cosine distance answers "are these two passages about the same thing?", which it is good at. It cannot answer "do these two passages disagree?", which is a question about meaning. A threshold-based version of this feature would be worse than not building it, because it would appear to work.

---

## 4. Nomination: take the top few by rank, not everything above a line

Given that similarity only nominates, how many candidates should each incoming chunk get?

The first attempt used a threshold: compare against everything scoring above 0.75. On a clone with a single edit this looked fine. On the finished clone with five edits it failed badly. Four of the twelve incoming chunks scored below 0.75 against their correct counterparts, and two of those four carried the most important edits. The cleaning-rule change scored 0.6316. The interference refinement matched the *wrong* chunk at 0.6298, with its actual counterpart sitting at rank two on **0.4454** — below plenty of genuinely unrelated pairs elsewhere in the same run.

At a 0.75 threshold, the two cases specifically designed to test the adjudicator would have been dropped before it ever ran.

The reason is worth understanding, because the first explanation offered was wrong. It was initially blamed on chunk boundaries cutting sentences awkwardly. The real cause is **topic blending**. A chunk that contains two unrelated topics gets an averaged embedding and matches on whichever topic takes up more room. In the clone, added text pushed the tail of the troubleshooting section into the same chunk as the entire warranty section. That chunk is mostly warranty text, so it matched the stored warranty chunk — and its true counterpart came second.

Several fixes were tried and none worked. Splitting on section headers moved the problem from four chunks to three. Sweeping chunk size from 200 to 1200 characters made the worst case range between 0.49 and 0.96 with no trend at all, because the outcome depends on where boundaries happen to land relative to the edits. That is not a tunable parameter, it is luck.

The fix was to stop gating on the score. For each incoming chunk, take the **top three candidates by rank regardless of what they score**, with a floor of 0.35 purely to skip obvious noise, and let the model decide all of them.

The asymmetry is what justifies it. Over-nominating costs a few model calls. Under-nominating silently loses information and you never find out. Those are not comparable risks.

A later cost analysis confirmed the same thing from the other direction. Sorted by verdict, the similarity ranges overlap thoroughly:

| Verdict | Similarity range |
|---|---|
| INDEPENDENT | 0.3571 – 0.6129 |
| REFINES | 0.4454 – 0.9234 |
| CONTRADICTS | 0.5639 – 0.9970 |

A floor of 0.44 would have saved four model calls and lost nothing — but only by a margin of 0.0004 against that interference pair. That is luck specific to one document, not a setting that generalises.

---

## 5. What, exactly, gets superseded?

Before anything can be retired, you need to say what a "thing" is.

The theoretically right unit is the **claim**: a single atomic assertion, like "the power button is held for five seconds". Claims are what actually contradict each other. If you tracked claims, you could retire exactly the sentence that changed and leave the rest of the paragraph alone.

Version 2 does not do this. The unit is the **chunk**, for two reasons: chunks already exist and claims would mean an extraction pipeline, a second store and a second set of correctness problems. Chunk size was raised to 800 characters so that a chunk usually holds a coherent section.

The cost of that choice is **collateral damage**. If a chunk holds four sentences and one of them is contradicted, retiring the chunk retires the other three too. This was accepted deliberately, with a written trigger: if collateral damage ever shows up in a real applied log, claim-level identity gets built. It was checked after the first real run and every line that disappeared was one the edits deliberately reversed. The trigger has not fired.

The ids also changed. In v1 they were positional — chunk 0, chunk 1, chunk 2 of a file — which means editing a paragraph near the top renumbers everything below it and every id points at different text than it did before. Ids are now **content-addressed**: the source filename plus the first twelve characters of the SHA-1 of the chunk text. An id now names a specific piece of text permanently.

This has a consequence that pays for itself repeatedly: **re-ingesting a document skips every chunk that did not change**, because the id is already in the store. Cost tracks how much was edited, not how big the document is.

---

## 6. Tombstones, never deletes

Nothing is ever removed from the store. A retired record keeps its text and its embedding and gains three pieces of metadata: `status` flips from `active` to `superseded`, `superseded_by` records the id of the chunk that replaced it, and `superseded_at` records when.

Retrieval then filters on `status: "active"`, which is a single line in the query and costs nothing.

The reason to tombstone rather than delete is that this feature is an automated system deciding, on a language model's judgment, that some of your knowledge is obsolete. It will sometimes be wrong. If being wrong means data is gone, the feature is not safe to run. If being wrong means a metadata flag needs flipping back, it is. Everything else — the log, the rollback tooling — exists to support that same principle.

---

## 7. The adjudicator

Each nominated pair is sent to Gemini with the older passage and the newer one clearly labelled, and one of four verdicts is required back:

- **DUPLICATE** — the later passage says the same thing. Nothing meaningful changed.
- **CONTRADICTS** — they cannot both be true or both be followed. A value changed, a prohibition was lifted, a fact was reversed.
- **REFINES** — the earlier passage is still true; the later one is more precise.
- **INDEPENDENT** — different subjects, neither affects the other.

A few details in that prompt are load-bearing. It says explicitly that sharing a topic or a heading is not a contradiction, because the pairs arriving have already been selected for looking alike. It says that if *any* statement in the later passage contradicts *any* statement in the earlier one the answer is CONTRADICTS even when everything else agrees, because chunks hold several sentences. It says that making a vague warning more specific is a refinement, and that permitting something previously forbidden is a contradiction — the two cases most often confused. And it asks the model to quote the sentence that drove its decision, which turns the log into something a human can audit.

The call runs at temperature 0 with a JSON schema constraining the response, so the verdict is always one of the four strings.

Two practical notes. **Byte-identical text never reaches the model** — if the incoming text exactly equals the stored text, it is marked DUPLICATE for free. On the test document that removed five of twelve chunks before any spending. And the free-tier quota is per minute, so a burst of calls returns `RESOURCE_EXHAUSTED`; the judge retries with exponential backoff.

Temperature 0 is not determinism, by the way. Two runs over identical inputs produced 16 INDEPENDENT and 6 REFINES the first time, 15 and 7 the second. One pair moved. That is exactly why the evaluation set exists.

---

## 8. The order of operations, which is easy to get wrong

```
chunk -> nominate -> adjudicate -> upsert -> apply -> log
```

Every arrow in that sequence is load-bearing.

**Nomination must come before the upsert.** If you store the incoming chunks first and then search for candidates, each new chunk finds *itself* in the store at similarity 1.0000 and nominates itself as its own duplicate. The batch would eat itself. This is prevented by ordering alone — there is no filter guarding it — so moving the upsert earlier breaks it silently.

**Applying must come after the upsert**, because `superseded_by` points at a chunk that has to actually exist before anything can point at it.

**Logging goes last.** In earlier phases it ran before the write, which was fine when nothing was ever written. Now each log line has to record whether the change was actually made, so it cannot be written until that is known.

---

## 9. Applying a verdict, and the guards around it

DUPLICATE and CONTRADICTS retire the older record. REFINES and INDEPENDENT do nothing. That is the whole rule, and almost all the engineering is in the guards around it.

**Only the older record can be retired.** If the incoming chunk turns out to be the older one — you are backfilling a historical document — the verdict is logged and nothing is applied. Otherwise a backfill could clobber current content, which is the recency mistake sneaking back in through a side door. Age comes from an explicit `--as-of` date rather than the wall clock, so the system can be tested against documents with dates in the past.

**One conflict produces several pairs, so targets are deduplicated.** A single real edit nominated the same stored chunk from two different incoming chunks. Grouping by the target id and acting once is what stops the same record being retired twice by different claimants; when several incoming chunks target the same stored one, the highest similarity wins and the choice is recorded.

**Applying twice is a no-op.** A record that is already superseded is skipped.

**A dry run can never apply.** The flag is refused at the command line and the apply call sits inside the branch that dry runs do not enter.

**And DUPLICATE only acts on byte-identical text.** This last guard was added because of a real failure sitting in the log. At similarity 0.4483 the model called the v2 *table of contents* a duplicate of the v1 **warranty section**, reasoning that the contents page lists warranty as its final item. Applied literally, the first production run would have silently removed the warranty text from retrieval because a contents page mentioned the word.

The reasoning for the fix is worth spelling out, because it looks superficially like the thresholding mistake this whole design rejects. It is not a threshold. "These two passages contradict each other" is a claim about meaning, and only a model can make it. "Nothing changed" is a claim about bytes, and a model is the wrong tool for it — `==` is exact, free and never hallucinates. So a duplicate the model merely asserts is logged and left alone, while CONTRADICTS is untouched by the guard. Similarity is still doing no adjudicating anywhere.

---

## 10. What it costs

Measured on a real run rather than estimated: 28 model calls, 15,589 input tokens, about 557 per call. Of that, **276 tokens per call is the fixed instruction block — 49% of all input is the same text sent over and over.**

The shape of the cost matters more than the number. Because ids are content-addressed, unchanged chunks are skipped before nomination. Re-ingesting a revision of a stored document costs in proportion to how much changed, not how long the document is. The same file ingested as a brand-new source produced 12 new chunks and 36 pairs; ingested as a revision of the existing one it produced 7 and 21. A 500-chunk manual with ten edited sections judges about fifteen chunks, not five hundred.

The expensive case is a large document's *first* entry into a populated store, where every chunk is new: roughly chunks × 3 calls.

Over half the spend — 16 of 28 calls — returned INDEPENDENT, confirming that unrelated things are unrelated. Tempting to optimise, but note *which* pairs those were. Not one candidate came from either of the two unrelated documents sharing the collection; vector search separates across documents perfectly well on its own. The waste is same-document comparisons, the specifications section against the packing list, which look alike because they share a heading style and a product name.

Three optimisations are safe and none are built: batch several pairs into one call so the instruction block is sent once, cache verdicts on the pair of content hashes so the same two passages are never judged twice, and use context caching on the instruction block if the tier supports it.

**All of this runs at ingest, never at query time.** Supersession is a fact about the store, not an opinion about a question. Decide once when writing and every future query gets the benefit through a metadata filter that costs nothing. Adjudicating at query time would mean a model call on every question forever, latency on every answer, a decision re-made and possibly re-decided each time, and no record of any of it. Ingests are rare and queries are constant, so the expensive thinking belongs on the rare side.

---

## 11. The audit trail, and why rollback needed a twin

Every pair ever considered is appended to `supersession_log.jsonl` — both passages, the similarity, the verdict, the model's quoted reasoning, whether it was applied, when, and if not, why not. That "why not" field matters as much as the rest: a line reading `duplicate judged by model, not byte-identical` is how you find out a guard is doing something.

The log is also the rollback path, which is why it is in version control. A rollback path that a `git clean` can destroy is not a rollback path.

`admin.py` reads it. `--list` shows what is retired and what replaced it, `--stats` counts by source and status, and `--rollback` replays the log backwards, restoring `status` to active and clearing the pointers.

Rollback was tested and it worked — and then exposed a problem. **It could not be undone.** Re-running the ingest to re-apply did nothing at all: the incoming chunks were already stored, so none were new, so nothing was nominated, so there was nothing left to act on. Content-addressing, which makes re-ingestion cheap, also makes it impossible to replay. The store was stranded in the rolled-back state with no route forward short of deleting chunks and paying for a fresh adjudication.

So `--reapply` replays the same log forwards, restoring the retirements and keeping the **original** timestamps, so the trail still records when the decision was made rather than when it was replayed. Both directions are idempotent. A rollback you cannot reverse is just a different way to lose your state.

---

## 12. What is still wrong

Worth knowing, and all of it is deliberate rather than overlooked.

**Same-source orphans linger.** If a section is deleted in version 2 of a document, nothing notices. Supersession only looks at what the new version contains, never at what it no longer contains. Catching this needs a different procedure — a set difference between two ingests of one source, needing no similarity search and no model call — and it is not built.

**The adjudicator sometimes narrates chunk boundaries as if they were edits.** Text landing in a different chunk in the new version has been described in a rationale as the later version "removing" a section. It produced harmless REFINES verdicts, but the same confusion producing a CONTRADICTS would retire good content.

**Rationales report only the first conflict they find.** A chunk holding two contradictions gets the right verdict with an incomplete explanation, which undercuts the log's job of justifying what was retired.

**One evaluation case has never passed.** A blanket ban on harsh chemicals becomes "isopropyl alcohol may be used, but only after the cushions have been detached". Read as a rule about chemicals that is a contradiction; read as cleaning advice it is a narrowing. The adjudicator consistently says REFINES. It is recorded as a known answer in the evaluation set so it cannot hide a real regression, and it is a fair illustration that some of these judgments are genuinely contested rather than simply right or wrong.

**Claim-level identity remains deferred**, with two independent arguments now supporting it — collateral damage, and the fact that chunk-level nomination cannot be made both complete and precise when a chunk blends topics. The trigger is still collateral damage in a real applied log, and it still has not fired.
