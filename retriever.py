"""
Retriever to get data from a vector store.
"""

from sentence_transformers import CrossEncoder
from store import documents, model

reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

def retrieve_and_rerank(query, k):
    retrieval_results = retrieve(query, 10)
    chunks = retrieval_results["documents"][0] # each field is a list of lists, [0] gives you the flat list for our query
    ids = retrieval_results["ids"][0]
    metadatas = retrieval_results["metadatas"][0]
    chunk_scores = reranker.predict([[query, chunk] for chunk in chunks])
    results = [{"id": chunk_id, "text": chunk, "metadata": metadata, "score": float(score)}
               for score, chunk_id, chunk, metadata in zip(chunk_scores, ids, chunks, metadatas)]
    results.sort(key = lambda result: result["score"], reverse = True)
    return results[:k]

def retrieve(query, k: int):
    query_embedding = model.encode([query]).tolist()
    similar_embeddings = documents.query(query_embeddings = query_embedding,
                    n_results = k,
                    where = {"status": "active"}) # superseded chunks stay stored, but must never reach the model
    return similar_embeddings
