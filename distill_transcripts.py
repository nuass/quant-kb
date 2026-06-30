#!/usr/bin/env python3
"""把 transcripts/*.{auc.md,merged.md} 用豆包 chat 蒸馏成结构化笔记 + QA。

输出: transcripts_distilled/<slug>.md
依赖环境变量: ARK_API_KEY
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ARK_CHAT_API = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
ARK_CHAT_MODEL = os.getenv("ARK_CHAT_MODEL", "doubao-1-5-pro-32k-250115")
ARK_API_KEY = os.getenv("ARK_API_KEY", "")

ROOT = Path(__file__).parent
SRC = ROOT / "transcripts"
DST = ROOT / "transcripts_distilled"
DST.mkdir(exist_ok=True)

TIME_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\s+-\s+\d{2}:\d{2}:\d{2}\]\s*")

SEG_MAX_CHARS = 28000
SEG_OVERLAP = 1500

SYSTEM_PROMPT = """你是量化平台课程的知识工程师。下面给你一段课程口语转写稿（可能是某节课的全文或一个长片段）。\
请提炼成结构化笔记，**严格按下面 Markdown 格式输出，不要任何额外说明**：

## 要点

- <一句话核心结论，覆盖本片段最重要的事实/规则/数字/术语定义>
- <…，10-20 条，去口语化重复，每条独立成立>

## QA

### Q: <一个可被独立检索的问题>
A: <2-5 句直接、可执行的回答，含具体阈值/操作/术语解释>

### Q: …
A: …

要求：
- 要点必须是陈述句，包含具体数字、术语、规则；不要"讲师说了…"这种元描述。
- QA 数量按片段实际信息密度，8-25 条都可以；问题要可被搜索引擎独立检索。
- 全部用中文。代码/表达式保留原样，用反引号。
- 如果片段几乎全是寒暄、广告、互动闲聊、无知识点，输出 `## 要点\\n\\n（无）\\n\\n## QA\\n\\n（无）` 即可，不要硬凑。"""


def strip_timestamps(text: str) -> str:
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("# "):
            continue
        m = TIME_RE.match(line)
        if m:
            lines.append(line[m.end():].strip())
        else:
            lines.append(line)
    return "\n".join(l for l in lines if l)


def chunk_text(text: str) -> list[str]:
    if len(text) <= SEG_MAX_CHARS:
        return [text]
    out = []
    i = 0
    while i < len(text):
        out.append(text[i:i + SEG_MAX_CHARS])
        if i + SEG_MAX_CHARS >= len(text):
            break
        i += SEG_MAX_CHARS - SEG_OVERLAP
    return out


def call_doubao(user_content: str, max_retry: int = 3) -> str:
    payload = {
        "model": ARK_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
    }
    last_err = None
    for attempt in range(1, max_retry + 1):
        try:
            r = requests.post(
                ARK_CHAT_API,
                headers={
                    "Authorization": f"Bearer {ARK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=300,
                proxies={"http": None, "https": None},
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            last_err = exc
            print(f"  retry {attempt}/{max_retry}: {exc}", file=sys.stderr)
            time.sleep(3 * attempt)
    raise RuntimeError(f"doubao chat failed after {max_retry}: {last_err}")


def lesson_title(stem: str) -> str:
    base = stem.split("_X")[0] if "_X" in stem else stem
    return base.replace("-", " ")


def merge_distilled(parts: list[str]) -> str:
    """多个片段的蒸馏结果合并：要点拼接 + QA 拼接，简单去重。"""
    bullets, qas = [], []
    bullet_seen, qa_seen = set(), set()
    for part in parts:
        section = None
        cur_q, cur_a = None, []
        for line in part.splitlines():
            s = line.rstrip()
            if s.startswith("## 要点"):
                section = "b"
                continue
            if s.startswith("## QA"):
                if cur_q is not None and cur_a:
                    key = cur_q.strip()
                    if key not in qa_seen and key != "（无）":
                        qa_seen.add(key)
                        qas.append((cur_q, "\n".join(cur_a).strip()))
                    cur_q, cur_a = None, []
                section = "q"
                continue
            if section == "b" and s.startswith("- "):
                v = s[2:].strip()
                if v and v not in bullet_seen and v != "（无）":
                    bullet_seen.add(v)
                    bullets.append(v)
            elif section == "q":
                if s.startswith("### Q:"):
                    if cur_q is not None and cur_a:
                        key = cur_q.strip()
                        if key not in qa_seen and key != "（无）":
                            qa_seen.add(key)
                            qas.append((cur_q, "\n".join(cur_a).strip()))
                    cur_q = s[len("### Q:"):].strip()
                    cur_a = []
                elif s.startswith("A:") and cur_q is not None:
                    cur_a.append(s[len("A:"):].strip())
                elif cur_q is not None and s:
                    cur_a.append(s)
        if cur_q is not None and cur_a:
            key = cur_q.strip()
            if key not in qa_seen and key != "（无）":
                qa_seen.add(key)
                qas.append((cur_q, "\n".join(cur_a).strip()))

    out = ["## 要点", ""]
    out += [f"- {b}" for b in bullets] if bullets else ["（无）"]
    out += ["", "## QA", ""]
    if qas:
        for q, a in qas:
            out.append(f"### Q: {q}")
            out.append(f"A: {a}")
            out.append("")
    else:
        out.append("（无）")
    return "\n".join(out).rstrip() + "\n"


def distill_one(md_path: Path) -> Path | None:
    title = lesson_title(md_path.stem)
    out_path = DST / f"{md_path.stem}.distilled.md"
    if out_path.exists():
        print(f"[skip] {out_path.name} already exists")
        return out_path

    raw = strip_timestamps(md_path.read_text(encoding="utf-8"))
    if not raw:
        print(f"[empty] {md_path.name}")
        return None

    segs = chunk_text(raw)
    print(f"[run ] {md_path.name} -> {len(segs)} segment(s), {len(raw)} chars")

    parts = []
    for i, seg in enumerate(segs, 1):
        prompt_prefix = f"课程标题: {title}\n片段 {i}/{len(segs)}\n\n转写正文:\n"
        out = call_doubao(prompt_prefix + seg)
        parts.append(out)
        print(f"  seg {i}/{len(segs)} done ({len(out)} chars)")

    merged = merge_distilled(parts)
    header = f"# {title}\n\n> 来源: transcripts/{md_path.name}\n\n"
    out_path.write_text(header + merged, encoding="utf-8")
    print(f"[ok  ] -> {out_path.name}")
    return out_path


def main() -> None:
    if not ARK_API_KEY:
        print("ARK_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    files = sorted(list(SRC.glob("*.auc.md")) + list(SRC.glob("*.merged.md")))
    print(f"Found {len(files)} transcripts under {SRC}")
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only:
        files = [f for f in files if only in f.name]
        print(f"Filtered to {len(files)} by '{only}'")

    for p in files:
        try:
            distill_one(p)
        except Exception as exc:
            print(f"[FAIL] {p.name}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
