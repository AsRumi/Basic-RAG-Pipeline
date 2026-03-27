from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(chunk_size = 100, 
                                          chunk_overlap = 20)

with open("document.txt") as f:
    doc_text = f.read()

# texts = splitter.create_documents([doc_text])

# print(f"Recursive Splitter Text: \n\n{splitter.split_text(doc_text)[:2]}")

def chunk_text(text, chunk_size, overlap):
    chunks = []
    i = 0
    while i < len(text):
        chunks.append(text[i: i + chunk_size])
        i += chunk_size - overlap
            
    return chunks