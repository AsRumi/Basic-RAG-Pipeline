import os
from dotenv import load_dotenv
from google import genai
from retriever import retrieve_and_rerank

load_dotenv()
client = genai.Client(api_key = os.getenv("GEMINI_API_KEY"))

def build_prompt(query, results):
    context = ""
    for result in results:
        context += result["text"] + "\n\n"
    
    instructions = "Answer the question at the end using only the given information below. Do not answer the question if the given information does not provide an answer. You can use the given information to construct sentences to answer the question."
    
    return instructions + "\n\n" + context + "\n\n" + query

def ask(query):
    results = retrieve_and_rerank(query, 3)
    prompt = build_prompt(query, results)
    response = client.models.generate_content(model = "gemini-3.5-flash-lite", contents = prompt)
    return response.text, results

if __name__ == "__main__":
    while True:
        question = input("Ask a question (Q/q to quit):\n")
        if question.lower() == "q":
            break
        else:
            answer, results = ask(question)
            print(answer)
            print("\nSources:")
            for result in results:
                print(f"  [{result['score']:+.2f}] {result['metadata']['source']} ({result['id']})")
            print()
