"""
Nominates candidate pairs, asks the model to judge them, and retires what they replace.
"""

import argparse
import json
import os
import re
import time
from collections import Counter
from google.genai import types
from llm import client, GEMINI_MODEL
from store import documents, model

CANDIDATES_PER_CHUNK = 3
SIMILARITY_FLOOR = 0.35
RETRIES = 4
BACKOFF = 8
LOG_PATH = "supersession_log.jsonl"
SUPERSEDING_VERDICTS = ("DUPLICATE", "CONTRADICTS")
NOT_APPLIED = "--apply not given"

VERDICT_SCHEMA = {"type": "object",
                  "properties": {"verdict": {"type": "string",
                                             "enum": ["DUPLICATE", "CONTRADICTS",
                                                      "REFINES", "INDEPENDENT"]},
                                 "rationale": {"type": "string"}},
                  "required": ["verdict", "rationale"]}

INSTRUCTIONS = """You are comparing two passages taken from different versions of the same documentation. Decide how the later passage relates to the earlier one, and answer with exactly one verdict.

DUPLICATE - the later passage says the same thing as the earlier one. Nothing meaningful has changed.

CONTRADICTS - the two cannot both be true or both be followed. Acting on the earlier passage would now give a wrong result: a value has changed, a prohibition has been lifted, or a stated fact has been reversed.

REFINES - the earlier passage is still true and the later one is simply more precise. It narrows the scope, adds a condition, or supplies extra detail, and nothing in the earlier passage becomes wrong.

INDEPENDENT - the passages are about different subjects and neither affects the other.

Rules:
- Sharing a topic, a heading or vocabulary is not by itself a contradiction.
- A passage may hold several statements. If any statement in the later passage contradicts any statement in the earlier one, answer CONTRADICTS even when everything else agrees.
- Making a vague warning more specific is REFINES, not CONTRADICTS.
- Permitting something the earlier passage forbade is CONTRADICTS, not REFINES.

Quote the sentence from each passage that drove your decision. Keep the rationale to two sentences."""

def nominate(chunks, source, ingested_at):
    if not chunks or documents.count() == 0:
        return []

    ids = list(chunks)
    texts = list(chunks.values())

    results = documents.query(query_embeddings = model.encode(texts).tolist(),
                              n_results = CANDIDATES_PER_CHUNK,
                              where = {"status": "active"})

    when = time.time()
    pairs = []

    for i, new_id in enumerate(ids):
        for old_id, old_text, old_metadata, distance in zip(results["ids"][i],
                                                            results["documents"][i],
                                                            results["metadatas"][i],
                                                            results["distances"][i]):
            similarity = 1 - distance # chroma reports cosine distance, not similarity
            identical = texts[i] == old_text
            pairs.append({"when": when,
                          "similarity": round(similarity, 4),
                          "nominated": similarity >= SIMILARITY_FLOOR,
                          "new_id": new_id,
                          "new_source": source,
                          "new_ingested_at": ingested_at,
                          "new_text": texts[i],
                          "old_id": old_id,
                          "old_source": old_metadata["source"],
                          "old_ingested_at": old_metadata["ingested_at"],
                          "old_text": old_text,
                          "older": "old" if old_metadata["ingested_at"] <= ingested_at else "new",
                          # byte-identical text needs no judgement, so it never reaches the model
                          "verdict": "DUPLICATE" if identical else None,
                          "rationale": "identical text" if identical else None,
                          "applied": False,
                          "applied_at": 0.0,
                          "skipped_reason": NOT_APPLIED})

    return pairs

def by_age(pair):
    if pair["older"] == "old":
        return pair["old_text"], pair["new_text"]
    return pair["new_text"], pair["old_text"]

def judge(earlier, later):
    prompt = (f"{INSTRUCTIONS}\n\nEARLIER PASSAGE:\n{earlier}"
              f"\n\nLATER PASSAGE:\n{later}")

    for attempt in range(RETRIES):
        try:
            response = client.models.generate_content(
                model = GEMINI_MODEL,
                contents = prompt,
                config = types.GenerateContentConfig(temperature = 0,
                                                     response_mime_type = "application/json",
                                                     response_schema = VERDICT_SCHEMA))
            return json.loads(response.text)
        except Exception as error:
            # the quota is per minute, so a burst of calls has to wait it out
            if "RESOURCE_EXHAUSTED" not in str(error) or attempt == RETRIES - 1:
                raise
            time.sleep(BACKOFF * 2 ** attempt)

def adjudicate(pairs):
    for pair in pairs:
        if not pair["nominated"] or pair["verdict"]:
            continue

        try:
            answer = judge(*by_age(pair))
            pair["verdict"] = answer["verdict"]
            pair["rationale"] = answer["rationale"]
        except Exception as error:
            pair["verdict"] = "ERROR"
            pair["rationale"] = f"{type(error).__name__}: {error}"[:300]
            print(f"  adjudication failed for {pair['new_id']}: {type(error).__name__}")

    return pairs

def skip_reason(pair):
    if not pair["nominated"]:
        return "below the similarity floor"
    if pair["verdict"] not in SUPERSEDING_VERDICTS:
        return f"verdict is {pair['verdict'] or 'UNJUDGED'}"
    if pair["older"] != "old":
        return "incoming chunk is older"
    # the model called a table of contents a duplicate of the section it listed, so an
    # unchanged-looking passage is only retired when the bytes actually match
    if pair["verdict"] == "DUPLICATE" and pair["new_text"] != pair["old_text"]:
        return "duplicate judged by model, not byte-identical"
    return ""

def apply(pairs):
    targets = {}
    for pair in pairs:
        pair["skipped_reason"] = skip_reason(pair)
        if not pair["skipped_reason"]:
            targets.setdefault(pair["old_id"], []).append(pair)

    if not targets:
        return pairs

    stored = documents.get(ids = list(targets))
    metadatas = dict(zip(stored["ids"], stored["metadatas"]))
    when = time.time()

    for old_id, contenders in targets.items():
        # one edit nominates the same stored chunk several times, and it is retired once
        winner = max(contenders, key = lambda pair: pair["similarity"])
        for loser in contenders:
            if loser is not winner:
                loser["skipped_reason"] = f"{winner['new_id']} won this target at {winner['similarity']:.4f}"

        old_metadata = metadatas.get(old_id)
        if old_metadata is None:
            winner["skipped_reason"] = "target not in the store"
        elif old_metadata["status"] != "active":
            winner["skipped_reason"] = "target already superseded"
        else:
            documents.update(ids = [old_id],
                             metadatas = [{**old_metadata,
                                           "status": "superseded",
                                           "superseded_by": winner["new_id"],
                                           "superseded_at": when}])
            winner["applied"] = True
            winner["applied_at"] = when

    return pairs

def log(pairs):
    with open(LOG_PATH, "a", encoding = "utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair) + "\n")

def read_log():
    if not os.path.exists(LOG_PATH):
        return []

    with open(LOG_PATH, encoding = "utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def preview(text, width = 68):
    flat = " ".join(re.sub(r"-{3,}", " ", text).split()) # section dividers crowd out the real text
    return flat if len(flat) <= width else flat[:width - 3] + "..."

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action = "store_true",
                        help = "Include pairs that fell below the similarity floor.")
    args, _ = parser.parse_known_args()

    pairs = read_log()
    if not pairs:
        raise SystemExit(f"No pairs logged yet. Run an ingest to populate {LOG_PATH}.")

    shown = pairs if args.all else [pair for pair in pairs if pair["nominated"]]
    shown.sort(key = lambda pair: (pair["verdict"] or "~", -pair["similarity"]))

    for pair in shown:
        print(f"{pair['verdict'] or 'UNJUDGED':12} {pair['similarity']:.4f}  "
              f"{pair['new_source']} -> {pair['old_source']}")
        print(f"    new: {preview(pair['new_text'])}")
        print(f"    old: {preview(pair['old_text'])}")
        if pair["rationale"]:
            print(f"    why: {preview(pair['rationale'], 100)}")
        if pair.get("applied"):
            print(f"    APPLIED: {pair['old_id']} superseded by {pair['new_id']}")
        elif pair.get("skipped_reason"):
            print(f"    not applied: {pair['skipped_reason']}")
        print()

    counts = Counter(pair["verdict"] or "UNJUDGED" for pair in shown)
    applied = sum(1 for pair in shown if pair.get("applied"))
    print(f"{len(shown)} shown of {len(pairs)} logged, {applied} applied")
    for verdict, n in counts.most_common():
        print(f"  {verdict}: {n}")
