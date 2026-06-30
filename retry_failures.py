#!/usr/bin/env python3
"""Retry failed AUC segments. Deletes old fail JSON and re-runs."""
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


def run_remote_auc(audio_url: str, env_file: str, max_poll: int, poll_int: int) -> dict:
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


def main() -> None:
    raw = Path('/Users/cony.zhangbjgmail.com/dev/wq-brain/knowledge/volc_auc/raw')
    env_file = "/root/xingsi-api/.env.stt"
    max_poll = 600
    poll_int = 5
    total_ok = total_fail = 0
    for lesson_dir in sorted([p for p in raw.iterdir() if p.is_dir()]):
        for json_path in sorted(lesson_dir.glob('*.json')):
            data = json.loads(json_path.read_text(encoding='utf-8'))
            if (data.get('text') or '').strip():
                continue
            url = data.get('url', '')
            if not url:
                continue
            print(f'retry {lesson_dir.name}/{json_path.name} -> {url}', flush=True)
            try:
                result = run_remote_auc(url, env_file, max_poll, poll_int)
                result = {k: v for k, v in data.items() if k not in ('error',)}
                result.update(run_remote_auc(url, env_file, max_poll, poll_int))
                json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                if result.get('text'):
                    print(f'  ok {len(result["text"])} chars', flush=True)
                    total_ok += 1
                else:
                    print(f'  still fail: {result.get("error", "empty")}', flush=True)
                    total_fail += 1
            except Exception as exc:
                print(f'  error {exc}', flush=True)
                total_fail += 1
            time.sleep(2)
    print(f'\ndone: ok={total_ok}, still_fail={total_fail}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
