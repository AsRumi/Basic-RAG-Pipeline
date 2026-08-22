import os
from dotenv import load_dotenv
from google import genai
from retriever import retrieve_and_rerank

load_dotenv()
client = genai.Client(api_key = os.getenv("GEMINI_API_KEY"))

def build_prompt(query, chunks):
    context = ""
    for chunk in chunks:
        context += chunk + "\n\n"
    
    instructions = "Answer the question at the end using only the given information below. Do not answer the question if the given information does not provide an answer. You can use the given information to construct sentences to answer the question."
    
    return instructions + "\n\n" + context + "\n\n" + query

def ask(query):
    chunks = retrieve_and_rerank(query, 3)
    prompt = build_prompt(query, chunks)
    response = client.models.generate_content(model = "gemini-3.5-flash-lite", contents = prompt)
    return response.text

if __name__ == "__main__":
    while True:
        question = input("Ask a question (Q/q to quit):\n")
        if question.lower() == "q":
            break
        else:
            print(ask(question))