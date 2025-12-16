import pdfplumber
import json
from openai import OpenAI

client = OpenAI()

PDF_PATH = "hr_policy.pdf"
OUTPUT_PATH = "hr_kb.json"

def chunk_text(text, chunk_size=500, overlap=100):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks

all_chunks = []

with pdfplumber.open(PDF_PATH) as pdf:
    for i, page in enumerate(pdf.pages):
        text = page.extract_text()
        if not text:
            continue

        chunks = chunk_text(text)
        for chunk in chunks:
            all_chunks.append({
                "page": i + 1,
                "text": chunk
            })

print(f"共產生 {len(all_chunks)} 個文字段落")

# 產生向量
for item in all_chunks:
    emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=item["text"]
    )
    item["embedding"] = emb.data[0].embedding

# 存成檔案
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(all_chunks, f, ensure_ascii=False)

print("HR 知識庫建立完成：hr_kb.json")
