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
TRANSCRIPT_DIR = Path(__file__).parent / "transcripts_distilled"
INDEX_PATH = Path(__file__).parent / "kb_index.json"
VECTORS_PATH = Path(__file__).parent / "kb_vectors.npy"
OFFICIAL_CACHE_PATH = Path(__file__).parent / "brain_official_cache.json"
OFFICIAL_VECTORS_PATH = Path(__file__).parent / "brain_official_vectors.npy"

ARK_EMB_API = "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
ARK_EMB_MODEL = "doubao-embedding-vision-251215"
ARK_EMB_KEY = os.getenv("ARK_EMB_KEY", "")

ARK_CHAT_API = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
ARK_CHAT_MODEL = "doubao-1-5-pro-32k-250115"
ARK_API_KEY = os.getenv("ARK_API_KEY", "")

# 相似度阈值：top-1 相似度低于此值时，直接返回"不知道"，不调用 LLM
DEFAULT_MIN_SIM = float(os.getenv("KB_MIN_SIM", "0.30"))

# 联网 fallback：本地 LLM 答"不知道"时改走联网搜索
WEB_FALLBACK_ENABLED = os.getenv("KB_WEB_FALLBACK", "1") == "1"
WEB_SEARCH_TIMEOUT = int(os.getenv("KB_WEB_SEARCH_TIMEOUT", "15"))
WEB_SEARCH_QUERY_PREFIX = os.getenv(
    "KB_WEB_QUERY_PREFIX",
    "WorldQuant BRAIN alpha 量化",
)
UNKNOWN_PATTERNS = (
    "不知道", "无法回答", "未提及", "没有提及",
    "没有相关", "未找到", "找不到", "未涉及",
    "没有信息", "未在", "无法从", "无法确定",
)

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

    # 2. 课程蒸馏笔记（transcripts_distilled/*.distilled.md）
    #    每个文件切成 1 个「要点合集」chunk + N 个 QA chunk（每个 Q+A 独立检索）
    for md_path in sorted(TRANSCRIPT_DIR.glob("*.distilled.md")):
        lesson_name = md_path.stem.replace(".distilled", "")
        lesson_name = lesson_name.split("_X")[0] if "_X" in lesson_name else lesson_name
        lesson_name = lesson_name.replace("-", " ")
        raw = md_path.read_text(encoding="utf-8")

        # 切分 ## 要点 与 ## QA 两段
        sec, bullets, qa_blocks = None, [], []
        cur_q, cur_a = None, []
        for line in raw.splitlines():
            s = line.rstrip()
            if s.startswith("## 要点"):
                sec = "bullet"; continue
            if s.startswith("## QA"):
                if cur_q is not None:
                    qa_blocks.append((cur_q, "\n".join(cur_a).strip()))
                    cur_q, cur_a = None, []
                sec = "qa"; continue
            if sec == "bullet" and s.startswith("- "):
                v = s[2:].strip()
                if v and v != "（无）":
                    bullets.append(v)
            elif sec == "qa":
                if s.startswith("### Q:"):
                    if cur_q is not None:
                        qa_blocks.append((cur_q, "\n".join(cur_a).strip()))
                    cur_q = s[len("### Q:"):].strip()
                    cur_a = []
                elif s.startswith("A:") and cur_q is not None:
                    cur_a.append(s[len("A:"):].strip())
                elif cur_q is not None and s:
                    cur_a.append(s)
        if cur_q is not None:
            qa_blocks.append((cur_q, "\n".join(cur_a).strip()))

        if bullets:
            chunks.append({
                "title": f"{lesson_name} - 要点",
                "content": "\n".join(f"- {b}" for b in bullets),
            })
        for q, a in qa_blocks:
            if not q or q == "（无）":
                continue
            chunks.append({
                "title": f"{lesson_name} - {q}",
                "content": f"Q: {q}\nA: {a}",
            })

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


def looks_unknown(answer: str) -> bool:
    if not answer:
        return True
    # 只有当答案非常短且匹配关键词，才认为是真的"不知道"。
    # 避免长答案里出现"未提及某个选项"这种局部短语被误判。
    cleaned = answer.strip()
    if len(cleaned) <= 40 and any(p in cleaned for p in UNKNOWN_PATTERNS):
        return True
    # 答案开头就是不知道
    head = cleaned[:60]
    starters = (
        "不知道", "无法回答", "无法从", "无法确定",
        "知识库中未", "知识库中没", "根据知识库", "知识库内",
    )
    # "根据知识库"/"知识库内"开头但答案短，且里面有否定关键词
    if any(head.startswith(s) for s in starters) and any(p in cleaned for p in UNKNOWN_PATTERNS):
        return True
    return False


def bing_search(query: str, top_n: int = 5) -> list[dict[str, str]]:
    """抓 cn.bing.com/search 前几条结果（标题+摘要+url）。无 key 免费。"""
    try:
        resp = requests.get(
            "https://cn.bing.com/search",
            params={"q": query, "ensearch": "0", "FORM": "BESBTB"},
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            timeout=WEB_SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"[bing] error: {e}")
        return []

    results: list[dict[str, str]] = []
    blocks = re.findall(
        r'<li[^>]*class="b_algo"[^>]*>(.+?)</li>',
        html, flags=re.DOTALL,
    )
    for block in blocks[: top_n * 2]:
        m_title = re.search(r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.+?)</a>', block, re.DOTALL)
        m_snippet = re.search(
            r'<(?:p|div)[^>]*class="b_(?:lineclamp|paractl|caption|snippet)[^"]*"[^>]*>(.+?)</(?:p|div)>',
            block, re.DOTALL,
        )
        if not m_title:
            continue
        url = m_title.group(1)
        title = re.sub(r"<[^>]+>", "", m_title.group(2)).strip()
        snippet = (
            re.sub(r"<[^>]+>", "", m_snippet.group(1)).strip()
            if m_snippet else ""
        )
        if not snippet:
            continue
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= top_n:
            break
    return results


def web_fallback_answer(question: str) -> dict[str, Any]:
    """知识库答不上时改走必应搜索 + 豆包总结。"""
    search_q = f"{WEB_SEARCH_QUERY_PREFIX} {question}" if WEB_SEARCH_QUERY_PREFIX else question
    hits = bing_search(search_q, top_n=5)
    if not hits:
        return {
            "answer": "知识库中未找到相关信息，且联网搜索未返回结果。",
            "web_results": [],
        }

    context_lines = []
    for i, h in enumerate(hits, 1):
        context_lines.append(f"[{i}] {h['title']}\n  URL: {h['url']}\n  摘要: {h['snippet']}")
    context = "\n\n".join(context_lines)

    system = (
        "你是 WorldQuant BRAIN 量化平台资深专家。下面是必应搜索得到的网页摘要，"
        "搜索摘要对 BRAIN 这种专业领域往往覆盖很差，常常无直接答案。"
        "**优先使用你对 WorldQuant BRAIN 的专业知识直接回答**，"
        "把搜索摘要当作可选参考。绝对不要回答\"摘要中没有\"或\"无法回答\"；"
        "必须给出你认为最可能正确的答案（选项题给字母+理由，表达式题给完整表达式）。"
        "最后一行用中文注明「答案部分依赖模型自身知识，未经官方文档验证，请以官方为准」。"
    )
    user = f"必应搜索摘要（仅供参考，可能无关）：\n\n{context}\n\n用户问题：{question}"

    if not ARK_API_KEY:
        return {
            "answer": f"[Ark API key not configured]\n\n联网搜索结果：\n\n{context}",
            "web_results": hits,
        }
    try:
        resp = requests.post(
            ARK_CHAT_API,
            headers={
                "Authorization": f"Bearer {ARK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": ARK_CHAT_MODEL,
                "max_tokens": 1024,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        answer = f"联网搜索成功，但 LLM 总结失败：{e}\n\n原始摘要：\n{context}"

    return {"answer": answer, "web_results": hits}


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
_official_chunks: list[dict[str, Any]] = []
_official_vectors: np.ndarray | None = None


def load_official_cache() -> tuple[list[dict[str, Any]], np.ndarray | None]:
    if not OFFICIAL_CACHE_PATH.exists() or not OFFICIAL_VECTORS_PATH.exists():
        print("[official] cache not found, official fallback disabled")
        return [], None
    chunks = json.loads(OFFICIAL_CACHE_PATH.read_text(encoding="utf-8"))
    vectors = np.load(OFFICIAL_VECTORS_PATH)
    print(f"[official] loaded {len(chunks)} chunks, vectors={vectors.shape}")
    return chunks, vectors


@app.on_event("startup")
def startup():
    global _chunks, _vectors, _official_chunks, _official_vectors
    _chunks, _vectors = load_index()
    _official_chunks, _official_vectors = load_official_cache()


def official_fallback_answer(question: str, q_emb: np.ndarray, top_k: int = 5) -> dict[str, Any]:
    """从 BRAIN 官方缓存（FAQ/operators/tutorials）里检索后让豆包总结。"""
    if _official_vectors is None or not _official_chunks:
        return {"answer": "", "hits": [], "ok": False}
    sims = []
    for i, vec in enumerate(_official_vectors):
        sims.append((cosine_similarity(q_emb, vec), i))
    sims.sort(reverse=True)
    top = sims[:top_k]

    contexts = []
    hits = []
    for sim, idx in top:
        c = _official_chunks[idx]
        contexts.append(f"【{c['title']}】(sim={sim:.3f})\n{c['content']}")
        hits.append({"title": c["title"], "similarity": round(float(sim), 4), "source": c.get("source", "")})
    ctx = "\n\n---\n\n".join(contexts)

    system = (
        "你是 WorldQuant BRAIN 平台官方文档助手。下面是从 BRAIN 官方 FAQ、Operator 目录、"
        "Tutorial 页面里检索到的权威内容。**请只依据这些官方内容回答**，"
        "不要编造、不要添加自己的猜测。若官方内容里确实没有相关信息，直接说\"官方文档中未涵盖该问题\"。"
        "选项题给字母+理由，表达式题给完整表达式。"
    )
    user = f"BRAIN 官方内容：\n\n{ctx}\n\n用户问题：{question}"
    if not ARK_API_KEY:
        return {"answer": f"[no ARK key]\n\n{ctx}", "hits": hits, "ok": True}
    try:
        resp = requests.post(
            ARK_CHAT_API,
            headers={"Authorization": f"Bearer {ARK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": ARK_CHAT_MODEL,
                "max_tokens": 1024,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return {"answer": f"官方检索失败：{e}", "hits": hits, "ok": False}
    return {"answer": answer, "hits": hits, "ok": True}


@app.post("/api/v1/brain-kb/query")
async def query(request: Request) -> dict[str, Any]:
    body = await request.json()
    question = body.get("question", "").strip()
    top_k = body.get("top_k", 3)
    min_sim = float(body.get("min_sim", DEFAULT_MIN_SIM))

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

    # 相似度阈值拦截：top-1 太低就直接说不知道，不调用 LLM
    if not top or top[0][0] < min_sim:
        rejected = {
            "question": question,
            "answer": "知识库中未找到与该问题相关的可靠信息，建议查阅官方文档或课程资料。",
            "sources": [
                {"title": _chunks[idx]["title"], "similarity": round(float(sim), 4)}
                for sim, idx in top
            ],
            "min_sim": min_sim,
            "top_sim": round(float(top[0][0]), 4) if top else 0.0,
            "rejected_by_threshold": True,
            "source": "kb",
            "official_hits": [],
            "web_results": [],
        }
        # 先试官方源
        official = official_fallback_answer(question, q_emb)
        if official["ok"] and not looks_unknown(official["answer"]) and "官方文档中未涵盖" not in official["answer"]:
            rejected["answer"] = official["answer"]
            rejected["official_hits"] = official["hits"]
            rejected["source"] = "official"
            return rejected
        # 官方源也没有 → web fallback
        use_web = bool(body.get("use_web", WEB_FALLBACK_ENABLED))
        if use_web:
            fb = web_fallback_answer(question)
            rejected["answer"] = fb["answer"]
            rejected["web_results"] = fb["web_results"]
            rejected["source"] = "web"
        return rejected

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

    source = "kb"
    web_results: list[dict[str, str]] = []
    official_hits: list[dict[str, Any]] = []
    use_web = bool(body.get("use_web", WEB_FALLBACK_ENABLED))
    if looks_unknown(answer):
        # 先试 BRAIN 官方源
        official = official_fallback_answer(question, q_emb)
        if official["ok"] and not looks_unknown(official["answer"]) and "官方文档中未涵盖" not in official["answer"]:
            answer = official["answer"]
            official_hits = official["hits"]
            source = "official"
        elif use_web:
            fb = web_fallback_answer(question)
            answer = fb["answer"]
            web_results = fb["web_results"]
            source = "web"

    return {
        "question": question,
        "answer": answer,
        "sources": [
            {"title": _chunks[idx]["title"], "similarity": round(float(sim), 4)}
            for sim, idx in top
        ],
        "source": source,
        "official_hits": official_hits,
        "web_results": web_results,
    }


_kb_html: str = ""


EXAM_TYPES = ("single", "multi", "truefalse", "expression", "fill", "auto")


def detect_question_type(question: str, options: list[str] | None) -> str:
    """根据题干和选项猜题型。"""
    if options and len(options) >= 2:
        # 多选关键词
        if any(k in question for k in ("多选", "哪些", "以下哪些", "选出所有")):
            return "multi"
        return "single"
    q = question.replace(" ", "")
    if any(k in q for k in ("正确还是错误", "对还是错", "判断", "T/F", "正确还是不正确")):
        return "truefalse"
    if any(k in q for k in ("写出", "写一个", "完整表达式", "Alpha 表达式", "表达式为", "公式")):
        return "expression"
    if any(k in q for k in ("填空", "____")):
        return "fill"
    # 短题干默认填空
    return "fill"


def build_exam_prompt(question: str, options: list[str] | None, qtype: str) -> str:
    """生成给 LLM 的提示词，要求返回 JSON。"""
    schema_hints = {
        "single": '{"choices":["A"], "rationale":"..."} （choices 只放一个字母）',
        "multi": '{"choices":["A","C"], "rationale":"..."} （字母去重升序）',
        "truefalse": '{"verdict":"正确" 或 "错误", "rationale":"..."}',
        "expression": '{"expression":"ts_mean(volume,10)", "rationale":"..."} （expression 只放纯表达式不带空格说明）',
        "fill": '{"value":"1.25", "rationale":"..."} （value 只放答题区直接填的内容）',
    }
    opt_text = ""
    if options:
        opt_text = "\n选项：\n" + "\n".join(options)
    return (
        f"题型：{qtype}\n题干：{question}{opt_text}\n\n"
        f"请只输出一个 JSON 对象，格式为：{schema_hints.get(qtype, schema_hints['fill'])}。"
        "不要任何额外文字、不要 markdown 代码块包裹。"
    )


def parse_exam_json(text: str) -> dict[str, Any]:
    """容错地解析 LLM 返回的 JSON。"""
    s = text.strip()
    # 去掉 ```json ``` 包裹
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    # 尝试找第一个 { ... }
    m = re.search(r"\{[\s\S]+\}", s)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        # 再容错：替换中文引号
        try:
            return json.loads(m.group(0).replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'"))
        except Exception:
            return {}


def gather_exam_context(question: str, q_emb: np.ndarray, top_k_kb: int = 5, top_k_off: int = 5) -> tuple[str, list[dict], list[dict], str]:
    """统一从 KB + 官方源拉取上下文。返回 (context_text, kb_hits, official_hits, primary_source)。"""
    sims_kb = sorted(
        [(cosine_similarity(q_emb, vec), i) for i, vec in enumerate(_vectors)] if _vectors is not None else [],
        reverse=True,
    )[:top_k_kb]
    sims_off = sorted(
        [(cosine_similarity(q_emb, vec), i) for i, vec in enumerate(_official_vectors)] if _official_vectors is not None else [],
        reverse=True,
    )[:top_k_off]

    parts = []
    kb_hits = []
    for sim, idx in sims_kb:
        c = _chunks[idx]
        parts.append(f"【KB:{c.get('title','')}】(sim={sim:.3f})\n{c.get('content','')}")
        kb_hits.append({"title": c.get("title", ""), "similarity": round(float(sim), 4)})
    off_hits = []
    for sim, idx in sims_off:
        c = _official_chunks[idx]
        parts.append(f"【BRAIN官方:{c.get('title','')}】(sim={sim:.3f})\n{c.get('content','')}")
        off_hits.append({"title": c.get("title", ""), "similarity": round(float(sim), 4), "source": c.get("source", "")})

    top_kb_sim = sims_kb[0][0] if sims_kb else 0.0
    top_off_sim = sims_off[0][0] if sims_off else 0.0
    primary = "kb" if top_kb_sim >= top_off_sim else "official"
    return "\n\n---\n\n".join(parts), kb_hits, off_hits, primary


@app.post("/api/v1/brain-kb/exam")
async def exam_answer(request: Request) -> dict[str, Any]:
    """考试自动化专用接口。输入题干（+选项+题型），返回结构化答案。

    入参：
      question: str           题干（必填）
      options:  list[str]     选项列表，每项形如 "A. xxx"（可选）
      type:     str           题型枚举: single|multi|truefalse|expression|fill|auto (默认 auto)
      include_rationale: bool 是否返回推理过程（默认 false，节省 token）
    """
    body = await request.json()
    question = (body.get("question") or "").strip()
    options = body.get("options") or []
    qtype = (body.get("type") or "auto").lower()
    include_rationale = bool(body.get("include_rationale", False))

    if not question:
        return {"error": "question is required"}
    if qtype == "auto" or qtype not in EXAM_TYPES:
        qtype = detect_question_type(question, options)

    if not ARK_API_KEY:
        return {"error": "ARK_API_KEY not configured"}

    # 1. 向量检索
    full_q = question + ("\n" + "\n".join(options) if options else "")
    q_emb = np.array(get_embedding(full_q), dtype=np.float32)
    ctx, kb_hits, off_hits, primary = gather_exam_context(question, q_emb)

    # 2. 用 LLM 出结构化答案
    prompt = build_exam_prompt(question, options, qtype)
    system = (
        "你是 WorldQuant BRAIN Consultant 考试自动化助手。根据下面提供的 KB 与官方文档上下文，"
        "**严格按要求的 JSON schema 输出**。优先依据上下文中的事实；上下文不足时再用你对 BRAIN 平台的通识。"
        "无论如何必须给出答案，不允许返回'未知'。"
    )
    user = f"上下文：\n\n{ctx}\n\n{prompt}"
    try:
        resp = requests.post(
            ARK_CHAT_API,
            headers={"Authorization": f"Bearer {ARK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": ARK_CHAT_MODEL,
                "max_tokens": 512,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return {"error": f"LLM call failed: {e}"}

    parsed = parse_exam_json(raw)

    # 3. 规整出 answer 字段（自动化最常用）
    answer = ""
    if qtype == "single":
        ch = parsed.get("choices") or []
        answer = ch[0] if ch else ""
    elif qtype == "multi":
        ch = parsed.get("choices") or []
        answer = "".join(sorted({c.strip().upper()[:1] for c in ch if c}))
    elif qtype == "truefalse":
        v = (parsed.get("verdict") or "").strip()
        answer = "正确" if v in ("正确", "true", "True", "T", "对") else ("错误" if v in ("错误", "false", "False", "F", "错") else v)
    elif qtype == "expression":
        answer = (parsed.get("expression") or "").strip()
    else:
        answer = (parsed.get("value") or "").strip()

    out = {
        "question": question,
        "type": qtype,
        "answer": answer,
        "parsed": parsed,
        "primary_source": primary,
        "kb_hits": kb_hits,
        "official_hits": off_hits,
    }
    if include_rationale:
        out["rationale"] = parsed.get("rationale", "")
        out["raw_llm"] = raw
    return out


@app.get("/api/v1/brain-kb/kb")
def get_kb() -> dict[str, Any]:
    global _kb_html
    if not _kb_html:
        _kb_html = md_to_html(KB_PATH.read_text(encoding="utf-8"))
    return {"html": _kb_html}


@app.get("/api/v1/brain-kb/full")
def get_full_kb() -> dict[str, Any]:
    """全量知识库目录：精简 KB + 课程转写 + BRAIN 官方 cache。"""
    handwritten: list[dict[str, str]] = []
    transcripts: list[dict[str, str]] = []
    for c in _chunks:
        title = c.get("title", "")
        item = {"title": title, "content": c.get("content", "")}
        # 课程转写的 title 含时间戳 [HH:MM:SS - ...]
        if re.search(r"\[\d{2}:\d{2}:\d{2}", title):
            transcripts.append(item)
        else:
            handwritten.append(item)

    official_by_kind: dict[str, list[dict[str, str]]] = {"faq": [], "operator": [], "tutorial": []}
    for c in _official_chunks:
        src = c.get("source", "")
        item = {
            "title": c.get("title", ""),
            "content": c.get("content", ""),
            "source_id": str(c.get("source_id", "")),
        }
        if "faq" in src:
            official_by_kind["faq"].append(item)
        elif "operator" in src:
            official_by_kind["operator"].append(item)
        elif "tutorial" in src:
            official_by_kind["tutorial"].append(item)

    return {
        "kb_handwritten": {"count": len(handwritten), "items": handwritten},
        "kb_transcripts": {"count": len(transcripts), "items": transcripts},
        "official_faq": {"count": len(official_by_kind["faq"]), "items": official_by_kind["faq"]},
        "official_operator": {"count": len(official_by_kind["operator"]), "items": official_by_kind["operator"]},
        "official_tutorial": {"count": len(official_by_kind["tutorial"]), "items": official_by_kind["tutorial"]},
        "total": len(_chunks) + len(_official_chunks),
    }


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
.kb-search{width:100%;padding:10px 14px;border:2px solid #e8ecf1;border-radius:8px;font-size:14px;margin-bottom:12px;outline:none}
.kb-search:focus{border-color:#4a90d9}
.kb-stats{font-size:13px;color:#666;margin-bottom:12px;text-align:center}
.kb-group{margin-bottom:12px;border:1px solid #e8ecf1;border-radius:8px;overflow:hidden;background:#fff}
.kb-group-head{padding:12px 16px;background:#f0f4f8;cursor:pointer;font-weight:600;color:#1a1a2e;display:flex;justify-content:space-between;align-items:center}
.kb-group-head:hover{background:#e6ecf2}
.kb-group-head .badge{background:#4a90d9;color:#fff;border-radius:12px;padding:2px 10px;font-size:12px;font-weight:normal}
.kb-group-body{display:none;max-height:50vh;overflow-y:auto}
.kb-group.open .kb-group-body{display:block}
.kb-item{padding:10px 16px;border-top:1px solid #f0f4f8;cursor:pointer}
.kb-item:hover{background:#f8fafc}
.kb-item-title{font-size:14px;color:#1a1a2e;font-weight:500}
.kb-item-content{display:none;margin-top:8px;padding:10px;background:#fafbfc;border-radius:6px;font-size:13px;color:#555;white-space:pre-wrap;line-height:1.6;max-height:300px;overflow-y:auto}
.kb-item.open .kb-item-content{display:block}
.source-tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;margin-left:8px;vertical-align:middle}
.source-tag.kb{background:#e3f2fd;color:#1565c0}
.source-tag.official{background:#fff3e0;color:#e65100}
.source-tag.web{background:#fce4ec;color:#ad1457}
.md-pre{background:#1e1e2e;color:#e4e4e4;padding:12px 14px;border-radius:8px;overflow-x:auto;margin:8px 0;font-size:13px;line-height:1.5}
.md-pre code{font-family:"SF Mono",Menlo,Consolas,monospace;background:transparent;color:inherit;padding:0}
.md-code{background:#f0f4f8;color:#c7254e;padding:2px 6px;border-radius:4px;font-family:"SF Mono",Menlo,Consolas,monospace;font-size:90%}
.md-h{margin:10px 0 6px;color:#1a1a2e;font-weight:600;line-height:1.4}
h1.md-h{font-size:18px}h2.md-h{font-size:16px}h3.md-h{font-size:15px}h4.md-h,h5.md-h,h6.md-h{font-size:14px}
.md-ul,.md-ol{margin:6px 0 6px 22px}
.md-ul li,.md-ol li{margin:3px 0;line-height:1.6}
.md-tbl{border-collapse:collapse;margin:10px 0;font-size:13px;width:100%}
.md-tbl th,.md-tbl td{border:1px solid #d0d7de;padding:6px 10px;text-align:left;vertical-align:top}
.md-tbl th{background:#f0f4f8;color:#1a1a2e;font-weight:600}
.answer p,.kb-item-content p{margin:6px 0;line-height:1.7}
.kb-item-content{white-space:normal !important}
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
    <div id="kb-container">
      <input class="kb-search" id="kb-search" placeholder="输入关键词过滤（标题或内容）..." oninput="onKbSearch(event)">
      <div id="kb-list"><div class="kb-loading">加载中...</div></div>
    </div>
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
    const r = await fetch(window.location.origin + '/api/v1/brain-kb/full');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    window._kbData = data;
    renderKb('');
  } catch (e) {
    container.innerHTML = '<div class="error" style="display:block">加载知识库失败: ' + e.message + '</div>';
  }
}

function escapeHtml(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function renderMd(src) {
  if (!src) return '';
  // 提取代码块 ```...``` 先占位，避免内部被其它规则破坏
  const blocks = [];
  let s = src.replace(/```([a-zA-Z0-9_+-]*)\\n([\\s\\S]*?)```/g, function(_, lang, code){
    blocks.push('<pre class="md-pre"><code>' + escapeHtml(code) + '</code></pre>');
    return '\\u0000BLOCK' + (blocks.length-1) + '\\u0000';
  });
  s = escapeHtml(s);
  // 行内代码
  s = s.replace(/`([^`\\n]+)`/g, '<code class="md-code">$1</code>');
  // 粗体
  s = s.replace(/\\*\\*([^*\\n]+)\\*\\*/g, '<strong>$1</strong>');
  // 按行处理标题/列表/段落
  const lines = s.split('\\n');
  const out = [];
  let inUl = false;
  let inOl = false;
  let para = [];
  let tableBuf = [];
  function flushPara(){ if(para.length){ out.push('<p>'+para.join('<br>')+'</p>'); para=[]; } }
  function flushList(){ if(inUl){out.push('</ul>'); inUl=false;} if(inOl){out.push('</ol>'); inOl=false;} }
  function flushTable(){
    if(!tableBuf.length) return;
    let rows = tableBuf.filter(l => !/^\\s*\\|[-:\\s|]+\\|\\s*$/.test(l));
    if(rows.length === 0){ tableBuf=[]; return; }
    let html2 = '<table class="md-tbl">';
    for(let i=0;i<rows.length;i++){
      const cells = rows[i].trim().replace(/^\\|/,'').replace(/\\|$/,'').split('|').map(c=>c.trim());
      const tag = i===0 ? 'th' : 'td';
      html2 += '<tr>';
      for(const c of cells) html2 += '<'+tag+'>'+c+'</'+tag+'>';
      html2 += '</tr>';
    }
    html2 += '</table>';
    out.push(html2);
    tableBuf=[];
  }
  for (const line of lines) {
    if (line.indexOf('\\u0000BLOCK') === 0) {
      flushPara(); flushList(); flushTable();
      const idx = parseInt(line.replace(/\\u0000BLOCK/,'').replace(/\\u0000/,''), 10);
      out.push(blocks[idx] || '');
      continue;
    }
    // 表格行（以 | 开头并以 | 结尾）
    if (/^\\s*\\|.*\\|\\s*$/.test(line)) {
      flushPara(); flushList();
      tableBuf.push(line);
      continue;
    } else if (tableBuf.length) {
      flushTable();
    }
    const m1 = line.match(/^(#{1,6})\\s+(.+)$/);
    if (m1) { flushPara(); flushList(); flushTable(); out.push('<h'+m1[1].length+' class="md-h">'+m1[2]+'</h'+m1[1].length+'>'); continue; }
    const m2 = line.match(/^\\s*[-*]\\s+(.+)$/);
    if (m2) { flushPara(); flushTable(); if(inOl){out.push('</ol>'); inOl=false;} if(!inUl){out.push('<ul class="md-ul">'); inUl=true;} out.push('<li>'+m2[1]+'</li>'); continue; }
    const m3 = line.match(/^\\s*\\d+\\.\\s+(.+)$/);
    if (m3) { flushPara(); flushTable(); if(inUl){out.push('</ul>'); inUl=false;} if(!inOl){out.push('<ol class="md-ol">'); inOl=true;} out.push('<li>'+m3[1]+'</li>'); continue; }
    if (line.trim() === '') { flushPara(); flushList(); flushTable(); continue; }
    flushList();
    para.push(line);
  }
  flushPara(); flushList(); flushTable();
  return out.join('');
}

function renderKb(filter) {
  const data = window._kbData;
  if (!data) return;
  const groups = [
    {key:'kb_handwritten', label:'手写精简知识库（按章节）', cls:'kb'},
    {key:'kb_transcripts', label:'课程转写（按时间段）', cls:'kb'},
    {key:'official_faq', label:'BRAIN 官方 FAQ', cls:'official'},
    {key:'official_operator', label:'BRAIN 官方 Operator', cls:'official'},
    {key:'official_tutorial', label:'BRAIN 官方 Tutorial', cls:'official'},
  ];
  const f = (filter || '').trim().toLowerCase();
  let html = '<div class="kb-stats">共 <b>' + data.total + '</b> 条索引内容';
  if (f) html += '（过滤："' + escapeHtml(filter) + '"）';
  html += '</div>';
  for (const g of groups) {
    const grp = data[g.key] || {count:0, items:[]};
    let items = grp.items;
    if (f) items = items.filter(it => (it.title+'\\n'+it.content).toLowerCase().includes(f));
    if (f && items.length === 0) continue;
    html += '<div class="kb-group' + (f ? ' open' : '') + '" data-group="1">';
    html += '<div class="kb-group-head" data-toggle="group">';
    html += '<span>' + g.label + ' <span class="source-tag ' + g.cls + '">' + g.cls + '</span></span>';
    html += '<span class="badge">' + items.length + (f ? '/' + grp.count : '') + '</span>';
    html += '</div><div class="kb-group-body">';
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      html += '<div class="kb-item" data-toggle="item">';
      html += '<div class="kb-item-title">' + escapeHtml(it.title) + '</div>';
      html += '<div class="kb-item-content">' + renderMd(it.content) + '</div>';
      html += '</div>';
    }
    html += '</div></div>';
  }
  const root = document.getElementById('kb-list');
  root.innerHTML = html;
  root.onclick = function(ev) {
    const head = ev.target.closest('[data-toggle="group"]');
    if (head) { head.parentNode.classList.toggle('open'); return; }
    const item = ev.target.closest('[data-toggle="item"]');
    if (item) { item.classList.toggle('open'); }
  };
}

function onKbSearch(ev) {
  renderKb(ev.target.value);
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
    document.getElementById('answer').innerHTML = renderMd(data.answer);
    let srcLines = [];
    const tag = data.source || 'kb';
    const tagLabel = {kb:'KB 知识库', official:'BRAIN 官方', web:'联网兜底'}[tag] || tag;
    srcLines.push('答案来源: [' + tagLabel + ']');
    if (data.sources && data.sources.length) {
      srcLines.push('KB 命中:');
      srcLines.push(...data.sources.map(s => `  • ${s.title} (sim ${s.similarity})`));
    }
    if (data.official_hits && data.official_hits.length) {
      srcLines.push('BRAIN 官方命中:');
      srcLines.push(...data.official_hits.map(s => `  • ${s.title} (sim ${s.similarity})`));
    }
    if (data.web_results && data.web_results.length) {
      srcLines.push('联网摘要:');
      srcLines.push(...data.web_results.map(s => `  • ${s.title} — ${s.url}`));
    }
    document.getElementById('sources').textContent = srcLines.join('\\n');
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
