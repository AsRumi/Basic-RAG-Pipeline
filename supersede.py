"""
Nominates candidate pairs for supersession. Decides nothing, changes nothing.
"""

import argparse
import json
import os
import re
import time
from store import documents, model

SIMILARITY_THRESHOLD = 0.75
CANDIDATES_PER_CHUNK = 5
LOG_PATH = "supersession_log.jsonl"

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
            pairs.append({"when": when,
                          "similarity": round(similarity, 4),
                          "nominated": similarity >= SIMILARITY_THRESHOLD,
                          "new_id": new_id,
                          "new_source": source,
                          "new_ingested_at": ingested_at,
                          "new_text": texts[i],
                          "old_id": old_id,
                          "old_source": old_metadata["source"],
                          "old_ingested_at": old_metadata["ingested_at"],
                          "old_text": old_text,
                          "older": "old" if old_metadata["ingested_at"] <= ingested_at else "new",
                          "verdict": None,
                          "rationale": None})

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
    parser.add_argument("--threshold", type = float, default = SIMILARITY_THRESHOLD,
                        help = "Re-evaluate the logged pairs at a different cutoff.")
    parser.add_argument("--all", action = "store_true",
                        help = "Show pairs below the threshold too.")
    args, _ = parser.parse_known_args()

    pairs = read_log()
    if not pairs:
        raise SystemExit(f"No pairs logged yet. Run an ingest to populate {LOG_PATH}.")

    pairs.sort(key = lambda pair: pair["similarity"], reverse = True)
    above = [pair for pair in pairs if pair["similarity"] >= args.threshold]

    for pair in (pairs if args.all else above):
        mark = "*" if pair["similarity"] >= args.threshold else " "
        print(f"{mark} {pair['similarity']:.3f}  {pair['new_source']} -> {pair['old_source']}"
              f"  (older: {pair['older']})")
        print(f"          new: {preview(pair['new_text'])}")
        print(f"          old: {preview(pair['old_text'])}")

    print(f"\n{len(above)} of {len(pairs)} pairs at or above {args.threshold}")

    for cutoff in (0.9, 0.85, 0.8, 0.75, 0.7, 0.6, 0.5):
        print(f"  >= {cutoff}: {sum(1 for pair in pairs if pair['similarity'] >= cutoff)}")
