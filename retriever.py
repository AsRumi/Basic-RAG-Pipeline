"""
Retriever to get data from a vector store.
"""

from ingest import documents
from ingest import model
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

def retrieve(query, k: int):
    query_embedding = model.encode([query]).tolist()
    similar_embeddings = documents.query(query_embeddings = query_embedding,
                    n_results = k)
    return similar_embeddings

query = "What building materials did early humans use?"
results = retrieve(query, 3)
print(results["documents"])