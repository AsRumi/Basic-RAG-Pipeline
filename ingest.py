"""
Script to chunk and embed a document.
"""

import argparse
import hashlib
import os
import time
from datetime import datetime, timezone
from langchain_text_splitters import RecursiveCharacterTextSplitter
from store import documents, model

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

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
    args, _ = parser.parse_known_args()

    source = os.path.basename(args.name) # ids must not depend on how the path was typed
    ingested_at = parse_as_of(args.as_of)

    with open(args.name, encoding = "utf-8") as f:
        doc_text = f.read()

    splitter = RecursiveCharacterTextSplitter(chunk_size = CHUNK_SIZE,
                                              chunk_overlap = CHUNK_OVERLAP)

    chunks = {}
    for chunk in splitter.split_text(doc_text):
        chunks.setdefault(chunk_id(source, chunk), chunk)

    stored = set(documents.get(ids = list(chunks))["ids"])
    new_chunks = {id: text for id, text in chunks.items() if id not in stored}

    if new_chunks:
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

    dated = datetime.fromtimestamp(ingested_at, timezone.utc)

    print(f"Ingestion Complete! {len(new_chunks)} new chunks from {source}, dated {dated:%Y-%m-%d}")
    print(f"{len(stored)} already stored, collection now holds {documents.count()} chunks")
