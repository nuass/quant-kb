#!/usr/bin/env python3
"""Finish remaining segments: lesson 4 last 3 + lesson 2 retries."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

KB_HOST = os.environ.get("KB_HOST", "127.0.0.1")
SSH_TARGET = f"root@{KB_HOST}"

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


def run_remote_auc(audio_url: str, env_file: str, max_poll: int = 600, poll_int: int = 5) -> dict:
    proc = subprocess.run(
        ["ssh", SSH_TARGET, "python3 -", env_file, audio_url, str(max_poll), str(poll_int)],
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


def upload_with_ssh(local_path: Path, remote_target: str, remote_dir: str, remote_name: str) -> None:
    remote_path = f"{remote_dir.rstrip('/')}/{remote_name}"
    last_error = None
    for attempt in range(1, 6):
        with local_path.open("rb") as f:
            proc = subprocess.run(
                ["ssh", remote_target, f"mkdir -p '{remote_dir}' && cat > '{remote_path}'"],
                stdin=f,
                check=False,
            )
        if proc.returncode == 0:
            return
        last_error = subprocess.CalledProcessError(proc.returncode, proc.args)
        time.sleep(min(30, attempt * 3))
    raise last_error or RuntimeError("ssh upload failed")


def main() -> None:
    seg_root = Path('/Users/cony.zhangbjgmail.com/dev/wq-brain/knowledge/volc_auc/segments')
    raw_root = Path('/Users/cony.zhangbjgmail.com/dev/wq-brain/knowledge/volc_auc/raw')
    env_file = "/root/xingsi-api/.env.stt"
    url_prefix = f"http://{KB_HOST}:8000/api/v1/audio"
    remote_dir = "/root/xingsi-api/audio_temp"

    # Lesson 4 missing segments
    lesson4_slug = "04-零基础学量化第四课_XNjQ0NTQwMjA5Ng"
    lesson4_seg_dir = seg_root / lesson4_slug
    lesson4_raw_dir = raw_root / lesson4_slug
    lesson4_raw_dir.mkdir(parents=True, exist_ok=True)

    # Find missing segments (no JSON)
    missing = []
    for wav in sorted(lesson4_seg_dir.glob('*.wav')):
        if not (lesson4_raw_dir / (wav.stem + '.json')).exists():
            missing.append(wav)

    total_ok = total_fail = 0

    for wav in missing:
        remote_name = f"brain_{lesson4_slug}_{wav.name}"
        public_url = f"{url_prefix.rstrip('/')}/{remote_name}"
        print(f"upload {wav.name}", flush=True)
        upload_with_ssh(wav, SSH_TARGET, remote_dir, remote_name)
        print(f"asr {wav.name}", flush=True)
        try:
            result = run_remote_auc(public_url, env_file)
            record = {
                "lesson": "04-《零基础学量化》第四课",
                "lesson_slug": lesson4_slug,
                "segment": wav.name,
                "public_name": remote_name,
                "url": public_url,
            }
            payload = {**record, **result}
            (lesson4_raw_dir / (wav.stem + '.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            if result.get('text'):
                print(f"  ok {len(result['text'])} chars", flush=True)
                total_ok += 1
            else:
                print(f"  fail: {result.get('error', 'empty')}", flush=True)
                total_fail += 1
        except Exception as exc:
            print(f"  error {exc}", flush=True)
            total_fail += 1
        time.sleep(2)

    # Lesson 2 retry failures
    lesson2_slug = "02-零基础学量化_第二课_XNjQ1Mjg5Mzk4NA"
    lesson2_raw_dir = raw_root / lesson2_slug
    for json_path in sorted(lesson2_raw_dir.glob('*.json')):
        data = json.loads(json_path.read_text(encoding='utf-8'))
        if (data.get('text') or '').strip():
            continue
        url = data.get('url', '')
        if not url:
            continue
        print(f"retry {lesson2_slug}/{json_path.name}", flush=True)
        try:
            result = run_remote_auc(url, env_file)
            payload = {k: v for k, v in data.items() if k not in ('error',)}
            payload.update(result)
            json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            if result.get('text'):
                print(f"  ok {len(result['text'])} chars", flush=True)
                total_ok += 1
            else:
                print(f"  still fail: {result.get('error', 'empty')}", flush=True)
                total_fail += 1
        except Exception as exc:
            print(f"  error {exc}", flush=True)
            total_fail += 1
        time.sleep(2)

    print(f"\ndone: ok={total_ok}, fail={total_fail}", flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
