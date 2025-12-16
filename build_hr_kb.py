import pdfplumber
import json
from openai import OpenAI
import os
import re
from datetime import datetime, timezone

client = OpenAI()

PDF_PATH = "hr_policy.pdf"
OUTPUT_PATH = "hr_kb.json"

# ===== 從檔名解析人資規章資訊 =====
ORIGINAL_FILENAME = os.getenv("HR_POLICY_FILENAME", PDF_PATH)
filename = os.path.basename(ORIGINAL_FILENAME)

# 支援格式：HR-103-04_出勤管理辦法_202509.pdf
m = re.match(r"(HR-\d+-\d+)_(.+)_(\d{6})\.pdf", filename)

if m:
    POLICY_CODE = m.group(1)      # HR-103-04
    POLICY_NAME = m.group(2)      # 出勤管理辦法
    POLICY_MONTH = m.group(3)     # 202509
else:
    POLICY_CODE = "未知版次"
    POLICY_NAME = "未知辦法"
    POLICY_MONTH = "未知月份"

META = {
    "policy_code": POLICY_CODE,
    "policy_name": POLICY_NAME,
    "policy_month": POLICY_MONTH,
    "source_filename": filename,
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

print(f"HR 知識庫建立完成：hr_kb.json（{POLICY_MONTH} / {POLICY_CODE} / {POLICY_NAME}）")
