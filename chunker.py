def chunk_text(text, chunk_size, overlap):
    chunks = []
    i = 0
    while i + chunk_size <= len(text):
        if i == 0:
            chunks.append(text[i: i + chunk_size])
            i += chunk_size
        else:
            chunks.append(text[i - overlap: i + chunk_size - overlap])
            i += chunk_size
            
    if i < len(text):
        if i == 0:
            chunks.append(text)
        else:
            chunks.append(text[i - overlap: ])
            
    return chunks