"""
Retriever to get data from a vector store.
"""

from ingest import documents
from ingest import model
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

def retrieve_and_rerank(query, k):
    retrieval_results = retrieve(query, 10)
    chunks = retrieval_results["documents"][0] # "documents" is a list of lists, [0] gives you the flat list of strings
    chunk_scores = reranker.predict([[query, chunk] for chunk in chunks])
    scored_chunks = zip(chunk_scores, chunks)
    sorted_chunks = sorted(scored_chunks, key = lambda x: x[0], reverse = True)
    results = [chunk for _, chunk in sorted_chunks[:k]]
    return results

def retrieve(query, k: int):
    query_embedding = model.encode([query]).tolist()
    similar_embeddings = documents.query(query_embeddings = query_embedding,
                    n_results = k)
    return similar_embeddings