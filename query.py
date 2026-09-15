from llm import client, GEMINI_MODEL
from retriever import retrieve_and_rerank

CONTEXT_CHUNKS = 6

INSTRUCTIONS = """Answer the question at the end using only the passages below. Each passage is labelled with the document it came from and the section it sits in.

A table of contents, a section list or a bare heading is not an answer. Ignore those passages and answer from the ones that carry the actual detail. Only say the passages do not answer the question when none of them do.

You can use the passages to construct sentences to answer the question."""

def build_prompt(query, results):
    context = ""
    for result in results:
        context += f"--- from {result['metadata']['source']} ---\n{result['text']}\n\n"

    return f"{INSTRUCTIONS}\n\n{context}\nQUESTION: {query}"

def ask(query):
    results = retrieve_and_rerank(query, CONTEXT_CHUNKS)
    prompt = build_prompt(query, results)
    response = client.models.generate_content(model = GEMINI_MODEL, contents = prompt)
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
