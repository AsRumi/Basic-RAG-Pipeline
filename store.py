"""
Shared embedding model and vector store handles.
"""

import chromadb
from sentence_transformers import SentenceTransformer

DB_PATH = "chroma_db"
SPACE = "cosine"

model = SentenceTransformer("all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path = DB_PATH)
documents = client.get_or_create_collection("documents",
                                            configuration = {"hnsw": {"space": SPACE}})

# get_or_create hands back an existing collection unchanged, so a store built on
# another metric would be used silently. The metric cannot be altered in place.
if documents.configuration["hnsw"]["space"] != SPACE:
    raise RuntimeError(f"{DB_PATH}/ is not a {SPACE} store. Delete it and re-ingest.")
