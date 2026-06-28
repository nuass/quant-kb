#!/usr/bin/env python3
"""Merge raw AUC JSON segments into per-lesson Markdown transcripts."""
import json
from pathlib import Path

RAW_DIR = Path('/Users/cony.zhangbjgmail.com/dev/wq-brain/knowledge/volc_auc/raw')
OUT_DIR = Path('/Users/cony.zhangbjgmail.com/dev/wq-brain/knowledge/transcripts')


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def merge_lesson(raw_dir: Path, out_file: Path, lesson_title: str) -> None:
    rows = []
    for path in sorted(raw_dir.glob('*.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        text = data.get('text', '').strip()
        if not text:
            continue
        start = data.get('start')
        end = data.get('end')
        rows.append((start, end, text))

    lines = [f"# {lesson_title}", ""]
    for start, end, text in rows:
        if start is None or end is None:
            lines.append(text)
        else:
            lines.append(f"[{fmt_time(float(start))} - {fmt_time(float(end))}] {text}")
        lines.append("")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n".join(lines).strip() + "\n", encoding='utf-8')
    print(f"merged {len(rows)} segments, {len(''.join(r[2] for r in rows))} chars -> {out_file}")


def main() -> None:
    for lesson_dir in sorted([p for p in RAW_DIR.iterdir() if p.is_dir()]):
        title = lesson_dir.name
        for stem in ['01-', '02-', '03-', '04-']:
            if stem in title:
                title = title.split(stem)[1].split('_X')[0]
                title = f"《零基础学量化》第{'一二三四'[int(stem[:2])-1]}课"
                break
        out = OUT_DIR / f"{lesson_dir.name}.auc.md"
        merge_lesson(lesson_dir, out, title)


if __name__ == '__main__':
    main()
