"""
Script to chunk and embed a document.
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
import chromadb

with open("document.txt") as f:
    doc_text = f.read()
    
splitter = RecursiveCharacterTextSplitter(chunk_size = 300,
                                          chunk_overlap = 50)

chunks = splitter.split_text(doc_text)

model = SentenceTransformer("all-MiniLM-L6-v2")

client = chromadb.Client()
documents = client.create_collection("documents")

embeddings = model.encode(chunks).tolist()

documents.add(ids = [str(x) for x in range(len(chunks))],
              documents = chunks,
              embeddings = embeddings)

print("Ingestion Complete!")