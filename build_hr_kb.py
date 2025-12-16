import pdfplumber
import json
from openai import OpenAI
import os
import re
from datetime import datetime, timezone

client = OpenAI()

PDF_PATH = "hr_policy.pdf"
OUTPUT_PATH = "hr_kb.json"

def parse_version(filename: str) -> str:
    # 從檔名抓 HR-103-03 這種版次
    m = re.search(r"(HR-\d{3}-\d{2})", filename, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # 抓不到就用去副檔名後的檔名
    return os.path.splitext(filename)[0]

# 由 GitHub Actions 傳入原始檔名；本機跑就會是 hr_policy.pdf
ORIGINAL_FILENAME = os.getenv("HR_POLICY_FILENAME", PDF_PATH)
POLICY_VERSION = parse_version(ORIGINAL_FILENAME)

META = {
    "policy_filename": ORIGINAL_FILENAME,
    "policy_version": POLICY_VERSION,
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
}

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
output = {
    "meta": META,
    "items": all_chunks
}

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"HR 知識庫建立完成：hr_kb.json（版次：{POLICY_VERSION}）")
