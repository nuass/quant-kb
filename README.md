# 量化知识库 & 检索服务

通用量化领域知识库 + 向量检索 + 结构化答题接口。

> 用途:量化平台学习、Alpha/策略设计辅助、自有知识沉淀。
> ⚠️ 不要用于实时代答任何带反作弊的官方考试。

## 知识覆盖

| 覆盖范围 | 说明 | 状态 |
|---|---|---|
| **BRAIN** | 手写知识库 + 课程转写 + 官方 FAQ/Operator/Tutorial cache | ✅ 已上线(本仓库首发覆盖范围) |
| A 股研报 / 策略库 | 卖方研报、产业链调研、策略复盘 | 🚧 规划中 |
| 行情 / 因子库 | 因子定义、回测结果、衰减监控 | 🚧 规划中 |

下面所有数据/接口描述当前默认指向 BRAIN 覆盖范围。

---

## 数据组成

| 来源 | 数量 | 文件 | 出处 |
|---|---|---|---|
| 手写精简知识库(按章节切分) | 10 chunks | `BRAIN_考试知识库.md` | 自有整理(平台学习笔记 + 真题复盘) |
| 课程蒸馏笔记 - 要点合集 | 14 chunks | `transcripts_distilled/*.distilled.md` 的 `## 要点` 段 | 课程口语转写经豆包 chat 提炼成结构化陈述句 |
| 课程蒸馏笔记 - QA | 399 chunks | 同上 `## QA` 段,每个 Q+A 一个 chunk | 同上;原始录播来源:零基础学量化 4 讲、带你读论文 3 讲、Super Alpha 入门、Consultant Training 2 讲、用户到顾问衔接课、Brain Lab 数据探索、AIAC 等;音频先经火山方舟 AUC 转写(`transcripts/*.auc.md` / `*.merged.md`,留作原材料不入库) |
| BRAIN 官方 FAQ | 173 chunks | `brain_official_cache.json` | `GET https://api.worldquantbrain.com/faqs`(需登录 cookie) |
| BRAIN 官方 Operator | 66 chunks | 同上 | `GET https://api.worldquantbrain.com/operators` |
| BRAIN 官方 Tutorial | 24 chunks | 同上 | `GET https://api.worldquantbrain.com/tutorial-pages/{id}`(先 `/tutorials` 拿索引) |
| **合计** | **686** | | |

> 拉取脚本:`fetch_brain_official.py`,凭据走 `brain_credentials.txt`(`BRAIN_CRED` 可覆盖路径)。
> 课程蒸馏脚本:`distill_transcripts.py`,读 `transcripts/` 输出 `transcripts_distilled/`;转写稿原文**不入向量库**,只把 LLM 提炼后的要点 + QA 入库,避免口语化噪音稀释检索分。
> 私有/受限内容仅做本地知识沉淀,不在仓库内分发原文。

向量:doubao-embedding-vision-251215,2048 维,余弦相似度暴搜(无 FAISS)。

---

## 检索级联

```
question → KB 向量检索(top-1)
            ├─ sim ≥ 0.30  → 走 KB + 豆包总结
            │   └─ 答案疑似"不知道" → BRAIN 官方 cache → 仍未答 → Bing 联网兜底
            └─ sim <  0.30 → 直接走 BRAIN 官方 cache → Bing
```

返回字段 `source` 标识答案来自 `kb / official / web` 哪一层。

---

## HTTP 接口

部署:`http://<KB_HOST>`(端口 80,systemd 管理,具体地址不公开)。

### 1. `POST /api/v1/brain-kb/exam` — 结构化答题(自动化推荐)

```python
import requests
r = requests.post(
    "http://<KB_HOST>/api/v1/brain-kb/exam",
    json={
        "question": "Consultant 通过的 Sharpe 最低要求？",
        "options": ["A. 0.5", "B. 0.7", "C. 1.0", "D. 1.25"],
        "type": "single",     # single | multi | truefalse | expression | fill | auto
        "include_rationale": False,
    },
    timeout=120,
    proxies={"http": None, "https": None},
)
print(r.json()["answer"])   # → "D"
```

`answer` 字段按题型规整:

| 题型 | 返回示例 |
|---|---|
| single | `"D"` |
| multi | `"BC"`(字母去重升序连写) |
| truefalse | `"正确"` / `"错误"` |
| expression | `"ts_mean(volume,10)"`(纯表达式) |
| fill | `"1.25"` |

完整响应还包括 `parsed`(LLM 原始 JSON)、`primary_source`、`kb_hits`、`official_hits`。

### 2. `POST /api/v1/brain-kb/query` — 自然语言问答

```bash
curl -X POST http://<KB_HOST>/api/v1/brain-kb/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"什么是 Fitness?","top_k":3}'
```

返回 `answer` + `sources` + `source`(kb/official/web)。

### 3. `GET /api/v1/brain-kb/full` — 全量知识库目录

返回 5 个分组(`kb_handwritten`、`kb_transcripts`、`official_faq`、`official_operator`、`official_tutorial`),每条含 `title` + `content`。

### 4. `GET /` — Web UI

浏览器直接打开:左 tab 搜索答案、右 tab 浏览知识库(关键词过滤 + 分组折叠 + markdown 渲染)。

---

## 关键文件

```
knowledge/
├── kb_server.py                    # FastAPI 服务主入口(端口 8500)
├── BRAIN_考试知识库.md             # 手写精简知识库
├── transcripts/                    # 课程转写
├── kb_index.json / kb_vectors.npy  # KB 索引(精简+转写)
├── brain_official_cache.json       # BRAIN 官方 cache(263 chunks)
├── brain_official_vectors.npy      # 官方源向量
├── fetch_brain_official.py         # 重建官方 cache(需 brain_credentials.txt)
├── query_exam.py                   # 本地 CLI 问答
├── test_exam_api.py                # /exam 接口 10 题回归
├── test_remote_exam.py             # /query 接口 10 题回归
└── check_confidence.py             # 检索相似度排查
```

---

## 本地起服务

```bash
export ARK_EMB_KEY=...              # 火山方舟 embedding key
export ARK_API_KEY=...              # 火山方舟 chat key
python3 kb_server.py                # 起在 0.0.0.0:8500
```

环境变量:

| 变量 | 默认 | 作用 |
|---|---|---|
| `ARK_EMB_KEY` | — | doubao-embedding 必填 |
| `ARK_API_KEY` | — | doubao-chat 必填 |
| `KB_MIN_SIM` | `0.30` | KB top-1 阈值,低于则走兜底 |
| `KB_WEB_FALLBACK` | `1` | 是否启用 Bing 兜底(`0` 关闭) |
| `KB_WEB_QUERY_PREFIX` | `"WorldQuant BRAIN alpha 量化"` | Bing 查询前缀 |

---

## 重建官方 cache

```bash
export ARK_EMB_KEY=...
python3 fetch_brain_official.py    # 拉 FAQ/Operator/Tutorial + embedding,产出 cache+vectors
```

需要 `brain_credentials.txt`(默认路径 `/Users/.../wq-brain/brain_credentials.txt`,可用 `BRAIN_CRED` 覆盖)。

---

## 测试

```bash
# 远程 /exam 接口
NO_PROXY='*' python3 test_exam_api.py

# 远程 /query 接口
NO_PROXY='*' python3 test_remote_exam.py

# 本地 CLI
python3 query_exam.py
```

当前回归基线:**/exam 8/10 严格匹配,9/10 实际正确**(剩 1 道是工程内部经验官方未收录)。

---

## 已知限制

- 无鉴权,任何拿到 IP 的人都能调
- 单进程,~50MB 内存,QPS 受 doubao 接口限速约束
- 联网兜底走必应,对 BRAIN 私有内容收录极差,基本只在 KB+官方都无命中时兜底
- macOS 调用需绕过本地代理:`NO_PROXY='*'` 或 `proxies={"http":None,"https":None}`
