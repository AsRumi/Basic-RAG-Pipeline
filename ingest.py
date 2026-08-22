"""
Script to chunk and embed a document.
"""

import argparse
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
import chromadb

model = SentenceTransformer("all-MiniLM-L6-v2")

client = chromadb.PersistentClient(path = "chroma_db")
documents = client.get_or_create_collection("documents")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default = "document.txt")
    args, _ = parser.parse_known_args()

    with open(args.name, encoding = "utf-8") as f:
        doc_text = f.read()

    splitter = RecursiveCharacterTextSplitter(chunk_size = 300,
                                              chunk_overlap = 50)

    chunks = splitter.split_text(doc_text)

    embeddings = model.encode(chunks).tolist()

    documents.upsert(ids = [f"{args.name}-{x}" for x in range(len(chunks))],
                     documents = chunks,
                     embeddings = embeddings)

    print(f"Ingestion Complete! {len(chunks)} chunks from {args.name}")
