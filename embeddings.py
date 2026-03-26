from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("all-MiniLM-L6-v2")

sentences = [
    "The dog chased the ball",
    "A puppy ran after a tennis ball",
    "The stock market crashed today",
    "The dog chased the ball"
]

embeddings = model.encode(sentences)

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

sim_01 = cosine_similarity(embeddings[0], embeddings[1])
sim_02 = cosine_similarity(embeddings[0], embeddings[2])
sim_03 = cosine_similarity(embeddings[0], embeddings[4])

print(f"Cos of first two: {sim_01}\nCos of first and third: {sim_02}\nCos of same sentences: {sim_03}")