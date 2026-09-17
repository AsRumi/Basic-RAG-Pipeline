# How I taught the store to maintain itself

This is a walkthrough of everything I changed in version 2 and why, meant to be read in order rather than consulted. It assumes you know what the v1 pipeline does: chunk a document, embed the chunks, store them, retrieve the nearest ones at query time, re-rank them, and hand them to a model. If that part is unfamiliar, read the README first.

I made ambivalent choices over nearly every design decision here, and I got several wrong the first time and had to correct them by measurement.

---

## 1. The problem: a vetor store that quietly rots

I usually describe a RAG store as a knowledge base. It behaves more like a filing cabinet that nobody ever cleans out, especially if that cabinet scales to a million files.

Suppose your internal documentation says, in a page written two years ago:

> Do not call function `createTimeSlots`.

And then, last month, somebody writes a newer page:

> Call `createTimeSlots` after calling `setTimeSlots`.

Both pages get chunked, embedded and stored. Both are about the same function, so both score highly against a question about it, and both get retrieved. The model now receives two instructions that cannot both be followed and produces something confident and wrong, or hedges and gives you both. Nothing in the pipeline noticed, because I hadn't built anything that was looking.

I could fix this by hand in a store of thirty chunks. I could not fix it by hand in a store of thirty thousand, and the moment I stopped fixing it by hand, the store would begin to decay. So the question I set out to answer in version 2 was: **can the store notice for itself that something it holds has been superseded, and retire it?**

---

## 2. My first instinct, and the three things wrong with it

My obvious first mechanism was to make recency win. Store a timestamp with every chunk, compute an age multiplier, and let newer records outrank older ones during retrieval. Add a second multiplier for how much I trust the source, so an official manual beats a forum post.

It was a reasonable first idea but it did not survive contact with the details.

**Recency is not truth.** A newer document is not automatically correct. It might be a draft, a partial note, or a backfill of something historical. Time is evidence about which of two statements is current, but it is not evidence about which is right. I can use it to decide _which record loses_ once a conflict is established, but I cannot use it to establish that a conflict exists.

**The multiplier cannot live inside the search.** The re-ranker is a cross-encoder, and its outputs are signed logits running from roughly −11 to +11. These are not scores in a nice zero-to-one range. If I multiply a chunk's score by an authority factor of 1.5, a good chunk at +6 becomes +9 and rises, but a bad chunk at −8 becomes −12 and falls further, while a bad chunk at −8 multiplied by an authority factor of _0.5_ becomes −4 and **rises**. Penalising a low-authority document would promote it. Any weighting of this kind has to be additive, so I had to abandon the entire idea.

**Another flaw I found that steered my approach massively: embeddings cannot see contradiction at all.** I have a lot to talk about this, so I gave it its own section.

---

## 3. Why similarity can nominate but never decide

Embeddings put semantically similar text close together. My intuition going in was that a contradiction ought to be far away, it says the opposite, after all.

It is not. Consider these two:

> Do not call `createTimeSlots`.

> Call `createTimeSlots` after calling `setTimeSlots`.

High similarity. They share almost every token. Good. I want them compared.

Now these two:

> Do not call `createTimeSlots`.

> Do not call `createTimeSlots` from a background thread.

_Also_ high similarity, and for the same reason. But this is a refinement. The rule still holds; it has only been narrowed. Retiring the first because the second exists would delete a true statement.

Turns out, bi-encoders are famously blind to negation. "X is thread-safe" and "X is not thread-safe" embed almost identically, because one token flipped in a sentence of ten barely moves the vector.

To be sure, I measured it on a real corpus, and the measurement was worse than my argument. I cloned a product manual and edited it to plant a flat contradictio. I changed the pairing instructions of a bluetooth headset from a five-second hold with a blue-and-red flash, to a ten-second hold with green-and-purple. Following the old version, the device does not pair. Then I embedded both versions and compared them:

| Pair                    | Cosine similarity |
| ----------------------- | ----------------- |
| Byte-identical chunks   | 1.0000            |
| The contradicting chunk | 0.9966            |

**The entire distance between "nothing changed" and "actively wrong" is 0.0034.**

There is no threshold I can fit into that gap. Any cutoff that catches the contradiction also catches every unchanged chunk in the document; any cutoff that excludes duplicates excludes the contradiction too. The two classes are not separable in this dimension. Not poorly separable, _not separable_.

So I split the architecture in two, and this is the most important idea in version 2:

> **Similarity nominates candidates for comparison. A language model issues the verdict.**

Cosine distance answers "are these two passages about the same thing?", which it is good at. It cannot answer "do these two passages disagree?", which is a question about meaning. If I had built a threshold-based version of this feature, it would have been worse than not building it, because it would have appeared to work.

---

## 4. Nomination: I take the top few by rank, not everything above a line

Given that similarity only nominates, how many candidates should each incoming chunk get?

I first tried a threshold: compare against everything scoring above 0.75. On a clone with a single edit this looked fine. On the finished clone with five edits it failed badly. Four of the twelve incoming chunks scored below 0.75 against their correct counterparts, and two of those four carried the most important edits. The interference refinement matched the _wrong_ chunk at 0.6298, with its actual counterpart sitting at rank two on **0.4454**; below plenty of genuinely unrelated pairs elsewhere in the same run.

At a 0.75 threshold, the two cases I had specifically designed to test the adjudicator would have been dropped before it ever ran.

Why this happened is important to know, because my first explanation was wrong. I initially blamed it on chunk boundaries cutting sentences awkwardly. The real cause is **topic blending**. A chunk that contains two unrelated topics gets an averaged embedding and matches on whichever topic takes up more room. In my clone, added text in the headset clone pushed the tail of the "troubleshooting section" into the same chunk as the entire "warranty" section. That chunk is mostly warranty text, so it matched the stored warranty chunk; and its true counterpart came second.

I tried several fixes and none worked. Splitting on section headers moved the problem from four chunks to three. Sweeping chunk size from 200 to 1200 characters made the worst case range between 0.49 and 0.96 with no trend at all, because the outcome depends on where boundaries happen to land relative to the edits. That meant trying to tune this was based more on luck than on a correct parameter.

My fix is to stop gating on the score. For each incoming chunk, I take the **top three candidates by rank regardless of what they score**, with a floor of 0.35 purely to skip obvious noise, and let the model decide all of them.

A later cost analysis I ran confirmed the same thing. Sorted by verdict, the similarity ranges overlap thoroughly:

| Verdict     | Similarity range |
| ----------- | ---------------- |
| INDEPENDENT | 0.3571 – 0.6129  |
| REFINES     | 0.4454 – 0.9234  |
| CONTRADICTS | 0.5639 – 0.9970  |

A floor of 0.44 would have saved me four model calls and lost nothing; but only by a margin of 0.0004 against that interference pair. I read that as luck specific to one document, not a setting that generalises.

---

## 5. What, exactly, do I supersede?

Before anything can be retired, I need to say what a "thing" is.

The theoretically right unit is the **claim**: a single atomic assertion, like "the power button is held for five seconds". Claims are what actually contradict each other. If I tracked claims, I could retire exactly the sentence that changed and leave the rest of the paragraph alone.

I chose not to do this in version 2. My unit is the **chunk**, for two reasons: chunks already exist, and claims would mean building an extraction pipeline, a second store, and a second set of correctness problems. I raised chunk size from 100 in v1 to 800 characters in v2, so that a chunk usually holds a coherent section.

The cost of that choice is **collateral damage**. If a chunk holds four sentences and one of them is contradicted, retiring the chunk retires the other three too. I accepted this deliberately, with a written trigger: if collateral damage ever shows up in a real applied log, I'll build claim-level identity. I checked after the first real run and every line that disappeared was one the edits deliberately reversed.

I also changed the ids. In v1 they were positional ; chunk 0, chunk 1, chunk 2 of a file ; which means editing a paragraph near the top renumbers everything below it and every id points at different text than it did before. I made ids **content-addressed**: the source filename plus the first twelve characters of the SHA-1 of the chunk text. An id now names a specific piece of text permanently.

This has a consequence that pays for itself repeatedly: **re-ingesting a document skips every chunk that did not change**, because the id is already in the store. Cost tracks how much was edited, not how big the document is.

---

## 6. Keep the chunk, never delete it

I never remove anything from the store. A retired record keeps its text and its embedding and gains three pieces of metadata: `status` flips from `active` to `superseded`, `superseded_by` records the id of the chunk that replaced it, and `superseded_at` records when.

Retrieval then filters on `status: "active"`, which is a single line in the query and costs nothing.

## I chose to tombstone rather than delete because this feature is an automated system deciding, on a language model's judgment, that some of your knowledge is obsolete. It will sometimes be wrong. If being wrong means data is gone, I don't think the feature is safe to run. If being wrong means a metadata flag needs flipping back, then it is safe. Everything else, the log, the rollback tooling, exists to support that same principle.

## 7. The adjudicator

I send each nominated pair to Gemini with the older passage and the newer one clearly labelled, and I require one of four verdicts back:

- **DUPLICATE** ; the later passage says the same thing. Nothing meaningful changed.
- **CONTRADICTS** ; they cannot both be true or both be followed. A value changed, a prohibition was lifted, a fact was reversed.
- **REFINES** ; the earlier passage is still true; the later one is more precise.
- **INDEPENDENT** ; different subjects, neither affects the other.

I say explicitly that sharing a topic or a heading is not a contradiction, because the pairs arriving have already been selected for looking alike. I say that if _any_ statement in the later passage contradicts _any_ statement in the earlier one the answer is CONTRADICTS even when everything else agrees, because chunks hold several sentences. I say that making a vague warning more specific is a refinement, and that permitting something previously forbidden is a contradiction; the two cases I saw confused most often. And I ask the model to quote the sentence that drove its decision, which made the log auditable.

I run the call at temperature 0 with a JSON schema constraining the response, so the verdict is always one of the four strings.

Two practical notes. I made sure **byte-identical text never reaches the model**; if the incoming text exactly equals the stored text, I mark it DUPLICATE for free. On my test document that removed five of twelve chunks before I'd spent anything. And the free-tier quota is per minute, so a burst of calls returns `RESOURCE_EXHAUSTED`; so the judge retries with exponential backoff.

---

## 8. The order of operations.

```
chunk -> nominate -> adjudicate -> upsert -> apply -> log
```

**Nomination must come before the upsert.** If I stored the incoming chunks first and then searched for candidates, each new chunk would find _itself_ in the store at similarity 1.0000 and nominate itself as its own duplicate. The batch would eat itself. I prevent this by ordering alone ; there is no filter guarding it ; so moving the upsert earlier would break it silently.

**Applying must come after the upsert**, because `superseded_by` points at a chunk that has to actually exist before anything can point at it.

**Logging goes last.** In earlier phases I ran it before the write, which was fine when nothing was ever written. Now each log line has to record whether the change was actually made, so I can't write it until that is known.

---

## 9. Applying a verdict, and the guards I built around it

DUPLICATE and CONTRADICTS retire the older record. REFINES and INDEPENDENT do nothing. That is the whole rule, and almost all my engineering effort went into the guards around it.

**Only the older record can be retired.** If the incoming chunk turns out to be the older one (you are backfilling a historical document), I log the verdict and apply nothing. Otherwise a backfill could clobber current content, which is the recency mistake sneaking back in through a side door. I take age from an explicit `--as-of` date rather than the wall clock, so I can test the system against documents with dates in the past.

**One conflict produces several pairs, so I deduplicate targets.** A single real edit nominated the same stored chunk from two different incoming chunks. I group by the target id and act once, which stops the same record being retired twice by different claimants; when several incoming chunks target the same stored one, the highest similarity wins and I record the choice.

**Applying twice is a no-op.** I skip a record that is already superseded.

**A dry run can never apply.** I refuse the flag at the command line and I keep the apply call inside the branch that dry runs do not enter.

**And DUPLICATE only acts on byte-identical text.** There is no reason to make an LLM call when the solution is deterministic.

---

## 10. What it costs me

Measured on a real run rather than estimated: 28 model calls, 15,589 input tokens, about 557 per call. Of that, **276 tokens per call is the fixed instruction block; 49% of all input is the same text sent over and over.**

Because ids are content-addressed, I skip unchanged chunks before nomination. Re-ingesting a revision of a stored document should cost in proportion to how much changed, not how long the document is. I ingested the same file as a brand-new source and got 12 new chunks and 36 pairs; ingested as a revision of the existing one it produced 7 and 21. A 500-chunk manual with ten edited sections judges about fifteen chunks and not five hundred.

The expensive case is a large document's _first_ entry into a populated store, where every chunk is new: roughly chunks × 3 calls.

Over half the spend (16 of 28 calls) returned INDEPENDENT, confirming that unrelated things are unrelated. I was tempted to optimise this away, but I noticed _which_ pairs those were. Not one candidate came from either of the two unrelated documents sharing the collection; vector search separates across documents perfectly well on its own. The waste is same-document comparisons, the specifications section against the packing list, which look alike because they share a heading style and a product name.

I've identified three safe optimisations but built none of them: batch several pairs into one call so the instruction block is sent once, cache verdicts on the pair of content hashes so I never judge the same two passages twice, and use context caching on the instruction block if the tier supports it.

**All of this runs at ingest, never at query time.** Supersession is a fact about the store, not an opinion about a question. I decide once when writing and every future query gets the benefit through a metadata filter. Adjudicating at query time would mean a model call on every question forever, latency on every answer, a decision re-made and possibly re-decided each time, and no record of any of it. Ingests are rare and queries are constant, so I put the expensive thinking on the rare side.

---

## 11. The audit trail, and why my rollback needed a twin

I append every pair ever considered to `supersession_log.jsonl`. Both passages, the similarity, the verdict, the model's quoted reasoning, whether it was applied, when, and if not, why not.

The log is also my rollback path, which is why I kept it in version control.

`admin.py` reads it. `--list` shows what is retired and what replaced it, `--stats` counts by source and status, and `--rollback` replays the log backwards, restoring `status` to active and clearing the pointers.

I tested rollback and it worked; and then it exposed a problem. **I could not undo it.** Re-running the ingest to re-apply did nothing at all: the incoming chunks were already stored, so none were new, so nothing was nominated, so there was nothing left to act on. Content-addressing, which makes re-ingestion cheap, also makes it impossible to replay. The store was stranded in the rolled-back state with no route forward short of deleting chunks and paying for a fresh adjudication.

So I built `--reapply` to replay the same log forwards, restoring the retirements and keeping the **original** timestamps, so the trail still records when I made the decision rather than when I replayed it. A rollback that you cannot reverse is just a different way to lose the state.

---

## 12. What I know is still wrong

Worth knowing, and all of it is deliberate on my part rather than overlooked.

**Same-source orphans linger.** If a section is deleted in version 2 of a document, nothing notices. Supersession only looks at what the new version contains, never at what it no longer contains. Catching this needs a different procedure; a set difference between two ingests of one source, needing no similarity search and no model call. I haven't built it.

**The adjudicator sometimes narrates chunk boundaries as if they were edits.** I've seen text landing in a different chunk in the new version described in a rationale as the later version "removing" a section. It produced harmless REFINES verdicts, but the same confusion producing a CONTRADICTS would retire good content.

**Rationales report only the first conflict they find.** A chunk holding two contradictions gets the right verdict with an incomplete explanation, which undercuts the log's job of justifying what I retired.

**One evaluation case has never passed for me.** Consider a document that imposes a blanket ban on harsh chemicals, but the revision becomes "isopropyl alcohol may be used, but only after the cushions have been detached". Read as a rule about chemicals that is a contradiction; read as cleaning advice it is a narrowing. The adjudicator consistently says REFINES. I recorded it as a known answer in the evaluation set so it can't hide a real regression, and I think it's a fair illustration that some of these judgments are genuinely contested rather than simply right or wrong.

**I've deferred claim-level identity**, with two independent arguments now supporting it in my mind; collateral damage, and the fact that chunk-level nomination cannot be made both complete and precise when a chunk blends topics. My trigger is still collateral damage in a real applied log.
