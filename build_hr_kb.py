from docx import Document
import json
from openai import OpenAI
import os
import re
from datetime import datetime, timezone
from pathlib import Path

client = OpenAI()

POLICIES_DIR = Path("policies")
OUTPUT_PATH = "hr_kb_index.json"

# 檔名格式：HR-103-03_出勤管理辦法_202509.docx、QP-212-07_國內外出差管理辦法_202509.docx
FILENAME_RE = re.compile(r"^([A-Z]{2}-\d{3}-\d{2})_(.+)_(\d{6})\.docx$", re.IGNORECASE)


def chunk_text(text: str, chunk_size: int = 700, overlap: int = 120):
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + chunk_size)
        chunks.append(text[start:end])
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks


def read_docx_text(path: Path) -> str:
    doc = Document(str(path))
    parts = []

    # 段落
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if t:
            parts.append(t)

    # 表格（重要：很多規章的條款/表單在表格）
    for table in doc.tables:
        for row in table.rows:
            cells = [(c.text or "").strip() for c in row.cells]
            cells = [c for c in cells if c]
            if cells:
                parts.append(" | ".join(cells))

    return "\n".join(parts)


def parse_meta_from_filename(filename: str):
    m = FILENAME_RE.match(filename)
    if m:
        policy_code = m.group(1).upper()
        policy_name = m.group(2).strip()
        policy_month = m.group(3)
    else:
        policy_code = "未知版次"
        policy_name = Path(filename).stem
        policy_month = "未知月份"
    return policy_month, policy_code, policy_name


def embed_text(text: str):
    emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return emb.data[0].embedding


def main():
    if not POLICIES_DIR.exists():
        raise FileNotFoundError(f"找不到資料夾：{POLICIES_DIR}（請確認 repo 內有 /policies）")

    policy_files = sorted(
        [p for p in POLICIES_DIR.glob("*.docx") if p.name.lower() != ".gitkeep"],
        key=lambda p: p.name
    )

    if not policy_files:
        raise FileNotFoundError("policies/ 內找不到任何 .docx（請把規章 .docx 上傳到 /policies）")

    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "policies_count": len(policy_files),
        "policies_dir": str(POLICIES_DIR),
        "schema": "hr_kb_index_v1"
    }

    items = []
    policy_summaries = []

    for path in policy_files:
        filename = path.name
        policy_month, policy_code, policy_name = parse_meta_from_filename(filename)

        full_text = read_docx_text(path)
        chunks = chunk_text(full_text)

        policy_summaries.append({
            "source_filename": filename,
            "policy_month": policy_month,
            "policy_code": policy_code,
            "policy_name": policy_name,
            "chunks": len(chunks),
        })

        for idx, ch in enumerate(chunks, start=1):
            item = {
                "source_filename": filename,
                "policy_month": policy_month,
                "policy_code": policy_code,
                "policy_name": policy_name,
                "chunk_id": idx,
                "text": ch
            }
            item["embedding"] = embed_text(ch)
            items.append(item)

        print(f"✅ {filename} -> {len(chunks)} chunks")

    output = {
        "meta": meta,
        "policies": policy_summaries,
        "items": items
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"🎉 建庫完成：{OUTPUT_PATH}")
    print(f"總 chunks：{len(items)}")


if __name__ == "__main__":
    main()
