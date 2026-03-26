def chunk_text(text, chunk_size, overlap):
    chunks = []
    i = 0
    while i < len(text):
        chunks.append(text[i: i + chunk_size])
        i += chunk_size - overlap
            
    return chunks

text = "abcdefghijklmnopqrstuvwxyz"
chunk_size = 6
overlap = 2

print(chunk_text(text, chunk_size, overlap))