#!/usr/bin/env python3
"""
BRAIN 考试知识库 - 向量检索后端
- 使用 Ark Embedding API 生成向量
- 使用 numpy 存储向量 + 暴力检索（数据量小，无需 FAISS）
- 调用 Ark Chat API 生成答案
"""
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

# ---- Config ----
KB_PATH = Path(__file__).parent / "BRAIN_考试知识库.md"
TRANSCRIPT_DIR = Path(__file__).parent / "transcripts"
INDEX_PATH = Path(__file__).parent / "kb_index.json"
VECTORS_PATH = Path(__file__).parent / "kb_vectors.npy"

ARK_EMB_API = "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
ARK_EMB_MODEL = "doubao-embedding-vision-251215"
ARK_EMB_KEY = os.getenv("ARK_EMB_KEY", "")

ARK_CHAT_API = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
ARK_CHAT_MODEL = "doubao-1-5-pro-32k-250115"
ARK_API_KEY = os.getenv("ARK_API_KEY", "")

# ---- Load or Build Index ----

def load_chunks() -> list[dict[str, Any]]:
    """Parse KB markdown + transcript files into chunks."""
    chunks: list[dict[str, Any]] = []

    # 1. 精简版知识库（按 ## 切分）
    text = KB_PATH.read_text(encoding="utf-8")
    current_title = ""
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_lines:
                chunks.append({
                    "title": current_title,
                    "content": "\n".join(current_lines).strip(),
                })
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        chunks.append({
            "title": current_title,
            "content": "\n".join(current_lines).strip(),
        })

    # 2. 完整转写稿（去掉时间戳，合并成约5000字符的chunk）
    TIME_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\s+-\s+\d{2}:\d{2}:\d{2}\]\s*")
    CHUNK_SIZE = 5000  # 字符
    CHUNK_OVERLAP = 200

    for md_path in sorted(TRANSCRIPT_DIR.glob("*.auc.md")):
        lesson_name = md_path.stem.split("_X")[0] if "_X" in md_path.stem else md_path.stem
        lesson_name = lesson_name.replace("-", " ")
        raw = md_path.read_text(encoding="utf-8")

        # 提取所有段落（去掉时间戳）
        segments: list[tuple[str, str]] = []  # (time_range, text)
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            m = TIME_RE.match(line)
            if m:
                time_range = m.group(0).strip().rstrip("]") + "]"
                body = line[m.end():].strip()
                if body:
                    segments.append((time_range, body))
            elif line.startswith("# "):
                continue  # skip title line
            else:
                segments.append(("", line))

        if not segments:
            continue

        # 合并成chunk
        buf_text = ""
        buf_start = ""
        for time_range, body in segments:
            if not buf_start:
                buf_start = time_range
            if buf_text:
                buf_text += "\n"
            buf_text += body
            if len(buf_text) >= CHUNK_SIZE:
                title = f"{lesson_name} {buf_start}" if buf_start else lesson_name
                chunks.append({"title": title, "content": buf_text})
                # overlap
                if len(buf_text) > CHUNK_OVERLAP:
                    buf_text = buf_text[-CHUNK_OVERLAP:]
                else:
                    buf_text = ""
                buf_start = time_range

        if buf_text:
            title = f"{lesson_name} {buf_start}" if buf_start else lesson_name
            chunks.append({"title": title, "content": buf_text})

    return chunks


def get_embedding(text: str) -> list[float]:
    resp = requests.post(
        ARK_EMB_API,
        headers={
            "Authorization": f"Bearer {ARK_EMB_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": ARK_EMB_MODEL,
            "input": [{"type": "text", "text": text}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["data"]["embedding"]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def md_to_html(text: str) -> str:
    """Simple markdown to HTML converter for the KB."""
    lines = text.splitlines()
    html: list[str] = []
    table_rows: list[str] = []
    in_list = False

    def render_bold(text: str) -> str:
        return re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        html.append('<table style="border-collapse:collapse;width:100%;margin:10px 0;font-size:14px">')
        for i, row in enumerate(table_rows):
            tag = "th" if i == 0 else "td"
            bg = 'background:#f0f4f8;' if i == 0 else ''
            cells = [render_bold(c.strip()) for c in row.strip().split("|")[1:-1]]
            html.append("<tr>")
            for cell in cells:
                html.append(f'<{tag} style="border:1px solid #d0d7de;padding:8px 10px;{bg}">{cell}</{tag}>')
            html.append("</tr>")
        html.append("</table>")
        table_rows = []

    def flush_list() -> None:
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("# ") and not line.startswith("## "):
            flush_table()
            flush_list()
            html.append(f'<h1 style="font-size:22px;color:#1a1a2e;margin:24px 0 12px">{line[2:].strip()}</h1>')
        elif line.startswith("## "):
            flush_table()
            flush_list()
            html.append(f'<h2 style="font-size:18px;color:#1a1a2e;margin:20px 0 10px;border-bottom:2px solid #4a90d9;padding-bottom:6px">{line[3:].strip()}</h2>')
        elif line.startswith("### "):
            flush_table()
            flush_list()
            html.append(f'<h3 style="font-size:15px;color:#333;margin:14px 0 8px">{line[4:].strip()}</h3>')
        elif line.strip().startswith("|") and line.strip().endswith("|"):
            flush_list()
            if re.fullmatch(r'\s*\|[-:\s|]+\|\s*', line):
                continue
            table_rows.append(line)
        elif line.strip().startswith("- "):
            flush_table()
            if not in_list:
                html.append('<ul style="margin:8px 0 8px 22px">')
                in_list = True
            item = line.strip()[2:]
            item = render_bold(item)
            html.append(f'<li style="margin:5px 0;line-height:1.6">{item}</li>')
        elif line.strip() == "---":
            flush_table()
            flush_list()
            html.append('<hr style="border:none;border-top:1px solid #e8ecf1;margin:16px 0">')
        elif not line.strip():
            flush_table()
            flush_list()
        else:
            flush_table()
            flush_list()
            text_line = line.strip()
            text_line = render_bold(text_line)
            html.append(f'<p style="margin:6px 0;line-height:1.7">{text_line}</p>')

    flush_table()
    flush_list()
    return "\n".join(html)


def build_index() -> tuple[list[dict[str, Any]], np.ndarray]:
    chunks = load_chunks()
    vectors = []
    print(f"Building index for {len(chunks)} chunks...")
    for i, chunk in enumerate(chunks):
        text = f"{chunk['title']}\n{chunk['content']}"
        emb = get_embedding(text)
        vectors.append(emb)
        print(f"  [{i+1}/{len(chunks)}] {chunk['title'][:40]}... dim={len(emb)}")
        time.sleep(0.5)
    vectors_np = np.array(vectors, dtype=np.float32)

    # Save
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    np.save(VECTORS_PATH, vectors_np)
    print(f"Index saved: {INDEX_PATH}, {VECTORS_PATH}")
    return chunks, vectors_np


def load_index() -> tuple[list[dict[str, Any]], np.ndarray]:
    if not INDEX_PATH.exists() or not VECTORS_PATH.exists():
        return build_index()
    with open(INDEX_PATH, encoding="utf-8") as f:
        chunks = json.load(f)
    vectors = np.load(VECTORS_PATH)
    print(f"Loaded index: {len(chunks)} chunks, vectors shape={vectors.shape}")
    return chunks, vectors


# ---- FastAPI App ----
app = FastAPI(title="BRAIN KB")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_chunks: list[dict[str, Any]] = []
_vectors: np.ndarray | None = None


@app.on_event("startup")
def startup():
    global _chunks, _vectors
    _chunks, _vectors = load_index()


@app.post("/api/v1/brain-kb/query")
async def query(request: Request) -> dict[str, Any]:
    body = await request.json()
    question = body.get("question", "").strip()
    top_k = body.get("top_k", 3)

    if not question:
        return {"error": "question is required"}
    if _vectors is None or len(_chunks) == 0:
        return {"error": "index not loaded"}

    # Embed question
    q_emb = np.array(get_embedding(question), dtype=np.float32)

    # Search top-k
    sims = []
    for i, vec in enumerate(_vectors):
        sim = cosine_similarity(q_emb, vec)
        sims.append((sim, i))
    sims.sort(reverse=True)
    top = sims[:top_k]

    contexts = []
    for sim, idx in top:
        chunk = _chunks[idx]
        contexts.append(f"【{chunk['title']}】\n{chunk['content']}")

    context_text = "\n\n---\n\n".join(contexts)

    # Generate answer with Claude
    system_prompt = (
        "你是一个 BRAIN Consultant 考试助手。根据下面的知识库内容，"
        "回答用户的问题。只使用知识库中的信息，不要编造。"
        "如果知识库中没有相关信息，请直接说明。"
    )
    user_prompt = f"知识库内容：\n\n{context_text}\n\n用户问题：{question}"

    if ARK_API_KEY:
        resp = requests.post(
            ARK_CHAT_API,
            headers={
                "Authorization": f"Bearer {ARK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": ARK_CHAT_MODEL,
                "max_tokens": 2048,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]
    else:
        answer = f"[Ark API key not configured]\n\n检索到的相关知识：\n\n{context_text}"

    return {
        "question": question,
        "answer": answer,
        "sources": [
            {"title": _chunks[idx]["title"], "similarity": round(float(sim), 4)}
            for sim, idx in top
        ],
    }


_kb_html: str = ""


@app.get("/api/v1/brain-kb/kb")
def get_kb() -> dict[str, Any]:
    global _kb_html
    if not _kb_html:
        _kb_html = md_to_html(KB_PATH.read_text(encoding="utf-8"))
    return {"html": _kb_html}


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BRAIN 考试知识库</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f7fa;color:#333;line-height:1.6;padding:20px}
.container{max-width:900px;margin:0 auto;background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,0.08);padding:32px}
h1{text-align:center;color:#1a1a2e;margin-bottom:4px;font-size:24px}
.subtitle{text-align:center;color:#666;font-size:14px;margin-bottom:20px}
.tabs{display:flex;justify-content:center;gap:8px;margin-bottom:20px;border-bottom:2px solid #e8ecf1;padding-bottom:8px}
.tab{padding:8px 20px;border-radius:20px;font-size:14px;cursor:pointer;background:#f0f4f8;color:#666;border:none;transition:all .2s}
.tab.active{background:#4a90d9;color:#fff}
.panel{display:none}
.panel.active{display:block}
.input-wrap{position:relative;margin-bottom:20px}
textarea{width:100%;min-height:120px;padding:16px;border:2px solid #e8ecf1;border-radius:10px;font-size:15px;resize:vertical;outline:none;transition:border-color .2s}
textarea:focus{border-color:#4a90d9}
button.action{width:100%;padding:14px;background:#4a90d9;color:#fff;border:none;border-radius:10px;font-size:16px;cursor:pointer;transition:background .2s}
button.action:hover{background:#357abd}
button.action:disabled{background:#a0b4c8;cursor:not-allowed}
.result{margin-top:24px;padding:20px;background:#f8fafc;border-radius:10px;border-left:4px solid #4a90d9;display:none}
.result.show{display:block}
.result h3{color:#1a1a2e;margin-bottom:12px;font-size:16px}
.result .answer{white-space:pre-wrap;font-size:15px;color:#333;line-height:1.8}
.result .sources{margin-top:16px;padding-top:16px;border-top:1px solid #e8ecf1;font-size:13px;color:#666}
.loading{text-align:center;color:#666;padding:20px;display:none}
.error{color:#e74c3c;background:#fdf2f2;padding:12px;border-radius:8px;margin-top:16px;display:none}
.kb-content{max-height:70vh;overflow-y:auto;padding:16px;background:#fafbfc;border-radius:10px;border:1px solid #e8ecf1;font-size:14px}
.kb-content h1{font-size:20px;color:#1a1a2e;margin:20px 0 12px}
.kb-content h2{font-size:17px;color:#1a1a2e;margin:16px 0 10px;border-bottom:2px solid #4a90d9;padding-bottom:4px}
.kb-content h3{font-size:15px;color:#333;margin:12px 0 8px}
.kb-content table{width:100%;border-collapse:collapse;margin:10px 0;font-size:13px}
.kb-content th,.kb-content td{border:1px solid #d0d7de;padding:8px 10px}
.kb-content th{background:#f0f4f8}
.kb-content ul{margin:8px 0 8px 22px}
.kb-content li{margin:5px 0;line-height:1.6}
.kb-content p{margin:6px 0;line-height:1.7}
.kb-content hr{border:none;border-top:1px solid #e8ecf1;margin:16px 0}
.kb-content strong{color:#1a1a2e}
.kb-loading{text-align:center;color:#666;padding:40px}
</style>
</head>
<body>
<div class="container">
  <h1>BRAIN Consultant 考试知识库</h1>
  <p class="subtitle">输入考试题目检索答案，或直接浏览完整知识库</p>
  <div class="tabs">
    <button class="tab active" id="tab-search" onclick="switchTab('search')">搜索答案</button>
    <button class="tab" id="tab-kb" onclick="switchTab('kb')">浏览知识库</button>
  </div>

  <div class="panel active" id="panel-search">
    <div class="input-wrap">
      <textarea id="question" placeholder="请输入题目...例如：什么是Alpha？Sharpe比率大于多少才能通过？"></textarea>
    </div>
    <button class="action" id="submit" onclick="ask()">获取答案</button>
    <div class="loading" id="loading">正在检索知识库并生成答案...</div>
    <div class="error" id="error"></div>
    <div class="result" id="result">
      <h3>答案</h3>
      <div class="answer" id="answer"></div>
      <div class="sources" id="sources"></div>
    </div>
  </div>

  <div class="panel" id="panel-kb">
    <div id="kb-container"><div class="kb-loading">加载中...</div></div>
  </div>
</div>
<script>
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.getElementById('panel-' + name).classList.add('active');
  if (name === 'kb' && !window._kbLoaded) {
    window._kbLoaded = true;
    loadKb();
  }
}

async function loadKb() {
  const container = document.getElementById('kb-container');
  try {
    const r = await fetch(window.location.origin + '/api/v1/brain-kb/kb');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    container.innerHTML = '<div class="kb-content">' + (data.html || '') + '</div>';
  } catch (e) {
    container.innerHTML = '<div class="error" style="display:block">加载知识库失败: ' + e.message + '</div>';
  }
}

async function ask() {
  const q = document.getElementById('question').value.trim();
  if (!q) { alert('请输入题目'); return; }
  document.getElementById('submit').disabled = true;
  document.getElementById('loading').style.display = 'block';
  document.getElementById('result').classList.remove('show');
  document.getElementById('error').style.display = 'none';
  try {
    const url = window.location.origin + '/api/v1/brain-kb/query';
    console.log('[KB] fetch:', url, 'protocol:', window.location.protocol);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 90000);
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q, top_k: 3}),
      signal: ctrl.signal
    });
    clearTimeout(timer);
    console.log('[KB] response status:', r.status);
    if (!r.ok) {
      const text = await r.text();
      throw new Error('HTTP ' + r.status + ': ' + text.slice(0, 200));
    }
    const data = await r.json();
    console.log('[KB] data:', data);
    if (data.error) throw new Error(data.error);
    document.getElementById('answer').textContent = data.answer;
    const src = data.sources.map(s => `• ${s.title} (相似度: ${s.similarity})`).join('\\n');
    document.getElementById('sources').textContent = '参考来源:\\n' + src;
    document.getElementById('result').classList.add('show');
  } catch (e) {
    console.error('[KB] error:', e);
    let msg = e.message;
    if (e.name === 'AbortError') msg = '请求超时（90秒），请检查网络或重试';
    if (e.name === 'TypeError') msg = '网络错误：' + e.message + '（可能是 HTTPS/HTTP 混合内容被浏览器拦截，请确保地址栏为 http:// 而非 https://）';
    document.getElementById('error').textContent = '错误: ' + msg;
    document.getElementById('error').style.display = 'block';
  } finally {
    document.getElementById('submit').disabled = false;
    document.getElementById('loading').style.display = 'none';
  }
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8500)
