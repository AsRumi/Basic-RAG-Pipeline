from sentence_transformers import SentenceTransformer
import chromadb

model = SentenceTransformer("all-MiniLM-L6-v2")

client = chromadb.Client()
collection = client.create_collection("sentences")

sentences = [
    "The dog chased the ball",
    "A puppy ran after a tennis ball",
    "The stock market crashed today"
]

embeddings = model.encode(sentences).tolist() # Convert to plain Python lists that is expected by ChromaDB

collection.add(documents = sentences, # Store original texts
               embeddings = embeddings,
               ids = [str(i) for i in range(len(sentences))]) # Every entry needs a unique string ID

query  = "A dog playing fetch"
q_embedding = model.encode([query]).tolist()

results = collection.query(query_embeddings = q_embedding,
                           n_results = 2)

print(results["documents"])