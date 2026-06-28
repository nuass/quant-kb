#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
DEFAULT_AUDIO_DIR = ROOT / "audio"
DEFAULT_WORK_DIR = ROOT / "volc_auc"
DEFAULT_TRANSCRIPT_DIR = ROOT / "transcripts"


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"env file not found: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def slugify(text: str) -> str:
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^0-9A-Za-z_\-一-鿿]+", "", text)
    return text[:90] or "audio"


def run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def duration_seconds(path: Path) -> float:
    result = run([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], capture=True)
    return float(result.stdout.strip())


def segment_audio(src: Path, out_dir: Path, segment_seconds: int, overlap_seconds: int) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    total = duration_seconds(src)
    step = segment_seconds - overlap_seconds
    if step <= 0:
        raise SystemExit("segment seconds must be greater than overlap seconds")

    items: list[dict[str, Any]] = []
    start = 0.0
    idx = 0
    while start < total - 0.5:
        end = min(start + segment_seconds, total)
        name = f"seg_{idx:04d}_{int(start):06d}_{int(end):06d}.wav"
        out = out_dir / name
        if not out.exists() or out.stat().st_size < 1024:
            run([
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-i",
                str(src),
                "-t",
                f"{end - start:.3f}",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(out),
            ])
        items.append({"index": idx, "start": start, "end": end, "path": out})
        idx += 1
        start += step
    return items


def upload_with_ssh(local_path: Path, remote_target: str, remote_dir: str, remote_name: str) -> None:
    remote_path = f"{remote_dir.rstrip('/')}/{remote_name}"
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, 6):
        with local_path.open("rb") as f:
            proc = subprocess.run(
                ["ssh", remote_target, f"mkdir -p {sh_quote(remote_dir)} && cat > {sh_quote(remote_path)}"],
                stdin=f,
                check=False,
            )
        if proc.returncode == 0:
            return
        last_error = subprocess.CalledProcessError(proc.returncode, proc.args)
        time.sleep(min(30, attempt * 3))
    raise last_error or RuntimeError("ssh upload failed")


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def build_public_url(segment: Path, lesson_slug: str, args: argparse.Namespace) -> tuple[str, str | None]:
    if not args.url_prefix:
        raise SystemExit("--url-prefix is required for direct Volc AUC calls")

    remote_name = f"brain_{lesson_slug}_{segment.name}"
    if args.ssh_target:
        if not args.remote_audio_dir:
            raise SystemExit("--remote-audio-dir is required with --ssh-target")
        upload_with_ssh(segment, args.ssh_target, args.remote_audio_dir, remote_name)
        return f"{args.url_prefix.rstrip('/')}/{remote_name}", remote_name

    if args.public_audio_dir:
        public_dir = Path(args.public_audio_dir).expanduser().resolve()
        public_dir.mkdir(parents=True, exist_ok=True)
        dest = public_dir / remote_name
        if not dest.exists() or dest.stat().st_size != segment.stat().st_size:
            shutil.copy2(segment, dest)
        return f"{args.url_prefix.rstrip('/')}/{remote_name}", remote_name

    return f"{args.url_prefix.rstrip('/')}/{segment.name}", None


REMOTE_AUC_CODE = r'''
import json
import os
import sys
import time
from pathlib import Path

import requests

env_file, audio_url, max_poll_seconds, poll_interval = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
for raw in Path(env_file).read_text(errors='ignore').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    if line.startswith('export '):
        line = line[7:].strip()
    key, value = line.split('=', 1)
    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

appid = os.getenv('VOLC_APPID', '')
token = os.getenv('VOLC_TOKEN', '')
resource_id = os.getenv('VOLC_RESOURCE_ID', 'volc.bigasr.auc')
if not appid or not token:
    print(json.dumps({'text': '', 'error': 'VOLC_APPID/VOLC_TOKEN missing on remote'}, ensure_ascii=False))
    raise SystemExit(0)

headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer; {token}',
    'X-Api-Resource-Id': resource_id,
    'X-Api-App-Key': appid,
    'X-Api-Access-Key': token,
}
payload = json.dumps({
    'app': {'appid': appid, 'token': token},
    'user': {'uid': 'brain-course'},
    'audio': {'format': 'wav', 'url': audio_url},
    'additions': {'language': 'zh-CN'},
})
s = requests.Session()
s.trust_env = False
try:
    submit = None
    for submit_attempt in range(5):
        submit = s.post('https://openspeech.bytedance.com/api/v1/auc/submit', data=payload, headers=headers, timeout=30).json()
        if submit.get('resp', {}).get('code') == 1000:
            break
        if 'Do not support appid' in str(submit) and submit_attempt < 4:
            time.sleep(2 + submit_attempt * 2)
            continue
        print(json.dumps({'text': '', 'error': f'submit failed: {submit}', 'result': submit}, ensure_ascii=False))
        raise SystemExit(0)
    if not submit or submit.get('resp', {}).get('code') != 1000:
        print(json.dumps({'text': '', 'error': f'submit failed: {submit}', 'result': submit}, ensure_ascii=False))
        raise SystemExit(0)
    task_id = submit['resp']['id']
    deadline = time.time() + max_poll_seconds
    last = {}
    while time.time() < deadline:
        time.sleep(poll_interval)
        last = s.post(
            'https://openspeech.bytedance.com/api/v1/auc/query',
            json={'appid': appid, 'token': token, 'id': task_id},
            headers=headers,
            timeout=20,
        ).json()
        code = last.get('resp', {}).get('code', 0)
        if code == 1000:
            resp = last.get('resp', {})
            utterances = resp.get('utterances') or []
            text = ''.join(u.get('text', '') for u in utterances if u.get('text')) or str(resp.get('text') or '')
            print(json.dumps({'task_id': task_id, 'text': text.strip(), 'result': last}, ensure_ascii=False))
            raise SystemExit(0)
        if code and code < 2000:
            if any(msg in str(last).lower() for msg in ('task not found', 'cannot find task')):
                continue
            print(json.dumps({'task_id': task_id, 'text': '', 'error': f'recognition failed: {last}', 'result': last}, ensure_ascii=False))
            raise SystemExit(0)
    print(json.dumps({'task_id': task_id, 'text': '', 'error': f'timeout after {max_poll_seconds}s', 'result': last}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({'text': '', 'error': f'{type(exc).__name__}: {exc}'}, ensure_ascii=False))
'''


def run_remote_auc(args: argparse.Namespace, audio_url: str) -> dict[str, Any]:
    if not args.ssh_target or not args.remote_env_file:
        raise RuntimeError("--ssh-target and --remote-env-file are required for remote AUC mode")
    proc = subprocess.run(
        [
            "ssh",
            args.ssh_target,
            "python3 -",
            args.remote_env_file,
            audio_url,
            str(args.max_poll_seconds),
            str(args.poll_interval),
        ],
        input=REMOTE_AUC_CODE,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"remote AUC command failed: {proc.stderr.strip() or proc.stdout.strip()}")
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("remote AUC command returned no output")
    return json.loads(lines[-1])


def submit_auc(session: requests.Session, appid: str, token: str, resource_id: str, audio_url: str) -> str:
    payload = json.dumps({
        "app": {"appid": appid, "token": token},
        "user": {"uid": "brain-course"},
        "audio": {"format": "wav", "url": audio_url},
        "additions": {"language": "zh-CN"},
    })
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer; {token}",
        "X-Api-Resource-Id": resource_id,
        "X-Api-App-Key": appid,
        "X-Api-Access-Key": token,
    }
    resp = session.post("https://openspeech.bytedance.com/api/v1/auc/submit", data=payload, headers=headers, timeout=30)
    data = resp.json()
    if data.get("resp", {}).get("code") != 1000:
        raise RuntimeError(f"submit failed: {data}")
    return data["resp"]["id"]


def query_auc(session: requests.Session, appid: str, token: str, resource_id: str, task_id: str, max_poll_seconds: int, poll_interval: int) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer; {token}",
        "X-Api-Resource-Id": resource_id,
        "X-Api-App-Key": appid,
        "X-Api-Access-Key": token,
    }
    deadline = time.time() + max_poll_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        time.sleep(poll_interval)
        resp = session.post(
            "https://openspeech.bytedance.com/api/v1/auc/query",
            json={"appid": appid, "token": token, "id": task_id},
            headers=headers,
            timeout=20,
        )
        last = resp.json()
        code = last.get("resp", {}).get("code", 0)
        if code == 1000:
            return last
        if code < 2000 and "task not found" not in str(last).lower():
            raise RuntimeError(f"recognition failed: {last}")
    raise TimeoutError(f"recognition timeout after {max_poll_seconds}s; last={last}")


def extract_text(result: dict[str, Any]) -> str:
    resp = result.get("resp", {})
    utterances = resp.get("utterances") or []
    parts = [u.get("text", "").strip() for u in utterances if u.get("text")]
    if parts:
        return "".join(parts)
    return str(resp.get("text") or "").strip()


def merge_lesson(raw_dir: Path, out_file: Path, lesson_title: str) -> None:
    rows = []
    for path in sorted(raw_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        text = data.get("text", "").strip()
        if not text:
            continue
        rows.append((data.get("start"), data.get("end"), text))

    lines = [f"# {lesson_title}", ""]
    for start, end, text in rows:
        if start is None or end is None:
            lines.append(text)
        else:
            lines.append(f"[{fmt_time(float(start))} - {fmt_time(float(end))}] {text}")
        lines.append("")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def transcribe(args: argparse.Namespace) -> None:
    for env_file in args.env_file or []:
        load_env_file(Path(env_file).expanduser())

    appid = args.appid or os.getenv("VOLC_APPID", "")
    token = args.token or os.getenv("VOLC_TOKEN", "") or os.getenv("VOLC_SPEECH_API_KEY", "")
    resource_id = args.resource_id or os.getenv("VOLC_RESOURCE_ID", "volc.bigasr.auc")
    if not args.prepare_only and not args.remote_env_file and (not appid or not token):
        raise SystemExit("VOLC_APPID and VOLC_TOKEN are required")

    audio_dir = Path(args.audio_dir).expanduser().resolve()
    work_dir = Path(args.work_dir).expanduser().resolve()
    transcript_dir = Path(args.transcript_dir).expanduser().resolve()
    segment_root = work_dir / "segments"
    raw_root = work_dir / "raw"
    manifest_root = work_dir / "manifests"
    manifest_root.mkdir(parents=True, exist_ok=True)

    audio_files = sorted(list(audio_dir.glob("*.mp3")) + list(audio_dir.glob("*.wav")) + list(audio_dir.glob("*.m4a")))
    if args.limit_lessons:
        audio_files = audio_files[:args.limit_lessons]
    if not audio_files:
        raise SystemExit(f"no audio files found in {audio_dir}")

    session = requests.Session()
    session.trust_env = False

    for audio in audio_files:
        lesson_slug = slugify(audio.stem)
        lesson_segment_dir = segment_root / lesson_slug
        lesson_raw_dir = raw_root / lesson_slug
        lesson_raw_dir.mkdir(parents=True, exist_ok=True)
        segments = segment_audio(audio, lesson_segment_dir, args.segment_seconds, args.overlap_seconds)
        if args.limit_segments:
            segments = segments[:args.limit_segments]

        manifest = []
        for item in segments:
            seg_path = item["path"]
            public_url, public_name = build_public_url(seg_path, lesson_slug, args)
            record = {
                "lesson": audio.stem,
                "lesson_slug": lesson_slug,
                "segment": seg_path.name,
                "public_name": public_name,
                "url": public_url,
                "start": item["start"],
                "end": item["end"],
            }
            manifest.append(record)

            out = lesson_raw_dir / f"{seg_path.stem}.json"
            if out.exists() and args.skip_existing:
                try:
                    old = json.loads(out.read_text(encoding="utf-8"))
                    if old.get("text"):
                        print(f"skip {audio.stem}/{seg_path.name}", flush=True)
                        continue
                except json.JSONDecodeError:
                    pass

            if args.prepare_only:
                print(f"prepared {audio.stem}/{seg_path.name} -> {public_url}", flush=True)
                continue

            print(f"asr {audio.stem}/{seg_path.name}", flush=True)
            try:
                if args.remote_env_file:
                    payload = {**record, **run_remote_auc(args, public_url)}
                    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    if payload.get("text"):
                        print(f"  ok {len(payload['text'])} chars", flush=True)
                    else:
                        print(f"  error {payload.get('error', 'empty result')}", flush=True)
                else:
                    task_id = submit_auc(session, appid, token, resource_id, public_url)
                    result = query_auc(session, appid, token, resource_id, task_id, args.max_poll_seconds, args.poll_interval)
                    text = extract_text(result)
                    payload = {**record, "task_id": task_id, "text": text, "result": result}
                    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"  ok {len(text)} chars", flush=True)
            except Exception as exc:
                payload = {**record, "text": "", "error": f"{type(exc).__name__}: {exc}"}
                out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  error {payload['error']}", flush=True)

        (manifest_root / f"{lesson_slug}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if not args.prepare_only:
            merge_lesson(lesson_raw_dir, transcript_dir / f"{lesson_slug}.auc.md", audio.stem)


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe BRAIN course audio with Volcengine OpenSpeech AUC.")
    parser.add_argument("--audio-dir", default=str(DEFAULT_AUDIO_DIR))
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR))
    parser.add_argument("--transcript-dir", default=str(DEFAULT_TRANSCRIPT_DIR))
    parser.add_argument("--segment-seconds", type=int, default=300)
    parser.add_argument("--overlap-seconds", type=int, default=5)
    parser.add_argument("--max-poll-seconds", type=int, default=600)
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--url-prefix", default=os.getenv("AUC_AUDIO_URL_PREFIX", ""))
    parser.add_argument("--public-audio-dir", default=os.getenv("AUC_PUBLIC_AUDIO_DIR", ""))
    parser.add_argument("--ssh-target", default=os.getenv("AUC_SSH_TARGET", ""))
    parser.add_argument("--remote-audio-dir", default=os.getenv("AUC_REMOTE_AUDIO_DIR", ""))
    parser.add_argument("--env-file", action="append")
    parser.add_argument("--remote-env-file", default=os.getenv("AUC_REMOTE_ENV_FILE", ""))
    parser.add_argument("--appid", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--resource-id", default="")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--limit-lessons", type=int, default=0)
    parser.add_argument("--limit-segments", type=int, default=0)
    args = parser.parse_args()
    transcribe(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
