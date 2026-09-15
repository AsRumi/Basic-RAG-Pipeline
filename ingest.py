"""
Script to chunk and embed a document.
"""

import argparse
import hashlib
import os
import time
from collections import Counter
from datetime import datetime, timezone
from prepare import split
from store import documents, model
from supersede import nominate, adjudicate, apply, log, LOG_PATH

def content_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def chunk_id(source, text):
    return f"{source}::{content_hash(text)[:12]}"

def parse_as_of(value):
    if value is None:
        return time.time()

    try:
        as_of = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise SystemExit(f"--as-of must look like YYYY-MM-DD, got '{value}'")

    return as_of.replace(tzinfo = timezone.utc).timestamp()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default = "document.txt")
    parser.add_argument("--as-of", dest = "as_of",
                        help = "Date this content is from (YYYY-MM-DD). Defaults to now.")
    parser.add_argument("--dry-run", dest = "dry_run", action = "store_true",
                        help = "Nominate and log candidates without storing anything.")
    parser.add_argument("--no-adjudicate", dest = "adjudicate", action = "store_false",
                        help = "Skip the model call and log candidates unjudged.")
    parser.add_argument("--apply", action = "store_true",
                        help = "Retire the records the verdicts replace. Off by default.")
    args, _ = parser.parse_known_args()

    if args.apply and args.dry_run:
        raise SystemExit("--apply cannot be combined with --dry-run")

    source = os.path.basename(args.name) # ids must not depend on how the path was typed
    ingested_at = parse_as_of(args.as_of)

    with open(args.name, encoding = "utf-8") as f:
        doc_text = f.read()

    chunks = {}
    for chunk in split(doc_text, source):
        chunks.setdefault(chunk_id(source, chunk), chunk)

    stored = set(documents.get(ids = list(chunks))["ids"])
    new_chunks = {id: text for id, text in chunks.items() if id not in stored}

    # nominated before the upsert, so a batch can never be compared against itself
    candidates = nominate(new_chunks, source, ingested_at)

    if args.adjudicate:
        adjudicate(candidates)

    if new_chunks and not args.dry_run:
        texts = list(new_chunks.values())
        documents.upsert(ids = list(new_chunks),
                         documents = texts,
                         embeddings = model.encode(texts).tolist(),
                         metadatas = [{"source": source,
                                       "ingested_at": ingested_at,
                                       "status": "active",
                                       "superseded_by": "",
                                       "superseded_at": 0.0,
                                       "content_hash": content_hash(text)} for text in texts])

        # superseded_by names an incoming chunk, so nothing can be retired until they are stored
        if args.apply:
            assert not args.dry_run
            apply(candidates)

    log(candidates) # last, so every line records whether the mutation actually happened

    dated = datetime.fromtimestamp(ingested_at, timezone.utc)
    nominated = [pair for pair in candidates if pair["nominated"]]
    verdicts = Counter(pair["verdict"] or "UNJUDGED" for pair in nominated)

    print(f"{'Dry run!' if args.dry_run else 'Ingestion Complete!'} "
          f"{len(new_chunks)} new chunks from {source}, dated {dated:%Y-%m-%d}")
    print(f"{len(stored)} already stored, collection now holds {documents.count()} chunks")
    print(f"{len(nominated)} of {len(candidates)} pairs nominated, logged to {LOG_PATH}")
    for verdict, n in sorted(verdicts.items()):
        print(f"  {verdict}: {n}")

    if args.apply:
        applied = [pair for pair in candidates if pair["applied"]]
        active = len(documents.get(where = {"status": "active"}, include = [])["ids"])
        print(f"{len(applied)} records superseded, {active} still active")
        for pair in applied:
            print(f"  {pair['old_id']} -> {pair['new_id']}")
