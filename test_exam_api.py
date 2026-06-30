#!/usr/bin/env python3
"""测 /exam 接口的 10 道题。"""
import json
import os
import requests

KB_HOST = os.environ.get("KB_HOST", "127.0.0.1")
API = f"http://{KB_HOST}/api/v1/brain-kb/exam"

CASES = [
    {"question":"Consultant 考试通过的 Sharpe 比率最低要求是多少？",
     "options":["A. 0.5","B. 0.7","C. 1.0","D. 1.25"], "type":"single", "expect":"D"},
    {"question":"以下哪个 operator 用于计算过去 N 天的排名？",
     "options":["A. ts_mean(x, d)","B. ts_rank(x, d)","C. rank(x)","D. ts_zscore(x, d)"], "type":"single", "expect":"B"},
    {"question":"POST /submit 返回 201/200 即表示 alpha 已成功提交上线，不需要再通过 /alphas/{id} 查询状态验证。",
     "type":"truefalse", "expect":"错误"},
    {"question":"写出一个 Alpha 表达式，计算 volume 的 10 日简单移动平均。",
     "type":"expression", "expect":"ts_mean(volume,10)"},
    {"question":"以下哪些字段属于 fundamental（基本面）数据？",
     "options":["A. volume","B. equity","C. cashflow_op","D. close"], "type":"multi", "expect":"BC"},
    {"question":"/check 端点返回 alpha 状态为 SELF_CORRELATION，此时最可靠的做法是什么？",
     "options":["A. 直接调用 /alphas/{id} 查询","B. 调用 /check 端点重新查询","C. 等待 5 分钟后直接 submit","D. 放弃该 alpha 重新写"],
     "type":"single", "expect":"B"},
    {"question":"写出计算 (equity + cashflow_op) / cap 在过去 20 天内排名的完整表达式。",
     "type":"expression", "expect":"ts_rank((equity+cashflow_op)/cap,20)"},
    {"question":"BRAIN 积分体系中，触发顾问邀请（Advisor Invitation）的积分门槛是多少？",
     "options":["A. 5000 分","B. 7500 分","C. 10000 分","D. 15000 分"], "type":"single", "expect":"C"},
    {"question":"Alpha 的 turnover（换手率）越高，通常意味着策略的交易频率越高、交易成本越大。",
     "type":"truefalse", "expect":"正确"},
    {"question":"Fitness 指标主要由哪三个维度综合计算得出？",
     "type":"fill", "expect":"Sharpe/Returns/Turnover"},
]


def main():
    correct = 0
    for i, c in enumerate(CASES, 1):
        r = requests.post(API, json={
            "question": c["question"],
            "options": c.get("options", []),
            "type": c["type"],
            "include_rationale": False,
        }, timeout=120, proxies={"http":None,"https":None})
        data = r.json()
        ans = data.get("answer", "")
        ok = "✓" if c["expect"].replace(" ","").lower() in ans.replace(" ","").lower() or ans.replace(" ","").lower() in c["expect"].replace(" ","").lower() else "✗"
        if ok == "✓": correct += 1
        print(f"[{ok}] Q{i} type={data.get('type')} primary={data.get('primary_source')}")
        print(f"     问: {c['question'][:60]}")
        print(f"     期望: {c['expect']}  实际: {ans!r}")
    print(f"\n=== {correct}/{len(CASES)} ===")


if __name__ == "__main__":
    main()
