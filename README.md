# 量化知识库 & 检索服务

通用量化领域知识库 + 向量检索 + 结构化答题接口。

> 用途:量化平台学习、Alpha/策略设计辅助、自有知识沉淀。
> ⚠️ 不要用于实时代答任何带反作弊的官方考试。

## 子模块

| 子模块 | 说明 | 状态 |
|---|---|---|
| **BRAIN**(WorldQuant Consultant 考试) | 手写知识库 + 课程转写 + 官方 FAQ/Operator/Tutorial cache | ✅ 已上线(本仓库首发模块) |
| A 股研报 / 策略库 | 卖方研报、产业链调研、策略复盘 | 🚧 规划中 |
| 行情 / 因子库 | 因子定义、回测结果、衰减监控 | 🚧 规划中 |

下面所有数据/接口描述当前默认指向 BRAIN 子模块。

---

## 数据组成

| 来源 | 数量 | 文件 |
|---|---|---|
| 手写精简知识库(按章节切分) | 11 chunks | `BRAIN_考试知识库.md` |
| 课程转写(0-用户到顾问衔接课、零基础学量化、读论文、Super Alpha 等) | 76 chunks | `transcripts/*.auc.md` / `*.merged.md` |
| BRAIN 官方 FAQ(authenticated `/faqs`) | 173 chunks | `brain_official_cache.json` |
| BRAIN 官方 Operator(`/operators`) | 66 chunks | 同上 |
| BRAIN 官方 Tutorial(`/tutorial-pages/{id}`) | 24 chunks | 同上 |
| **合计** | **350** | |

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

部署:`http://<KB_HOST>`(端口 80,systemd 管理)。

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

## 部署

服务器 `<KB_HOST>`,systemd 单元 `brain-kb.service`,代码部署在 `/root/brain-kb/`(目录名沿用旧名,未跟随 repo 改名,避免影响 systemd 单元路径)。

```bash
scp kb_server.py brain_official_cache.json brain_official_vectors.npy \
    root@<KB_HOST>:/root/brain-kb/
ssh root@<KB_HOST> systemctl restart brain-kb
```

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
