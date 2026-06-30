#!/usr/bin/env python3
"""测试远程知识库回答 10 道模拟题。"""
import os
import requests

KB_HOST = os.environ.get("KB_HOST", "127.0.0.1")
API_URL = f"http://{KB_HOST}/api/v1/brain-kb/query"

QUESTIONS = [
    "Consultant 考试通过的 Sharpe 比率最低要求是多少？选项：A. 0.5 B. 0.7 C. 1.0 D. 1.25",
    "以下哪个 operator 用于计算过去 N 天的排名？选项：A. ts_mean(x, d) B. ts_rank(x, d) C. rank(x) D. ts_zscore(x, d)",
    "POST /submit 返回 201/200 即表示 alpha 已成功提交上线，不需要再通过 /alphas/{id} 查询状态验证。正确还是错误？",
    "写出一个 Alpha 表达式，计算 volume 的 10 日简单移动平均。",
    "以下哪些字段属于 fundamental（基本面）数据？选项：A. volume B. equity C. cashflow_op D. close",
    "/check 端点返回 alpha 状态为 SELF_CORRELATION，此时最可靠的做法是什么？选项：A. 直接调用 /alphas/{id} 查询 B. 调用 /check 端点重新查询 C. 等待 5 分钟后直接 submit D. 放弃该 alpha 重新写",
    "写出计算 (equity + cashflow_op) / cap 在过去 20 天内排名的完整表达式。",
    "BRAIN 积分体系中，触发顾问邀请（Advisor Invitation）的积分门槛是多少？选项：A. 5000 分 B. 7500 分 C. 10000 分 D. 15000 分",
    "Alpha 的 turnover（换手率）越高，通常意味着策略的交易频率越高、交易成本越大。正确还是错误？",
    "Fitness 指标主要由哪三个维度综合计算得出？",
]


def query_remote(question: str):
    resp = requests.post(
        API_URL,
        json={"question": question, "top_k": 3},
        timeout=90,
        proxies={"http": None, "https": None},
    )
    resp.raise_for_status()
    return resp.json()


def main():
    print(f"测试远程知识库: {API_URL}")
    print("=" * 60)

    for i, q in enumerate(QUESTIONS, 1):
        print(f"\n【第 {i} 题】{q}")
        print("-" * 40)
        try:
            data = query_remote(q)
            if data.get("error"):
                print(f"接口错误: {data['error']}")
            else:
                print(f"答案: {data['answer']}")
                print(f"来源: {[s['title'][:40] for s in data.get('sources', [])]}")
        except Exception as e:
            print(f"请求失败: {e}")
        print("=" * 60)


if __name__ == "__main__":
    main()
