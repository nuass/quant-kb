# BRAIN Consultant 基础能力测试复习大全

基于《零基础学量化》四节课完整转写稿整理，涵盖所有关键概念、定义、数字阈值与平台规则。

---

## 一、Alpha 核心概念

### 1.1 Alpha 的定义
- **Alpha** 是 BRAIN 平台自定义的术语（≠ 金融学传统 Alpha），指一个**数学公式/数学模型**，每天计算出一个值，对股票未来回报具有预测性。
- Alpha 的本质 = **Operator（运算符） + Data（数据字段）+ 参数** 的组合。
- 每天根据 Alpha 值，经过 Neutralization → Normalization，最终算出**权重（Weight）**，决定每只股票投多少钱。

### 1.2 两大 Idea 类型
| 类型 | 中文 | 含义 |
|---|---|---|
| **Momentum** | 动量 | 越高越好，好的越好（如资产负债率越高涨得越好） |
| **Reversal** | 反转/均值回归 | 越高越差，物极必反（如过去涨太多明天该跌了） |

### 1.3 两种计算维度
- **Cross-sectional（横截面）**：A 公司与 B 公司、C 公司之间横向比较（如 rank、group_rank）。
- **Time Series（时间序列）**：自己跟自己比，现在跟过去比（如 ts_rank、ts_mean、ts_delta）。

---

## 二、平台设置（Settings）详解

| 设置项 | 含义与考点 |
|---|---|
| **Region** | 回测区域（如 USA、China）。不同区域可用的 Data Field 不同，回测速度也可能不同。 |
| **Universe** | 股票池（如 TOP3000、TOP2000）。表示在多少只股票中选股。 |
| **Delay（DK）** | **Decay** 的简写，持仓衰减/线性加权平均天数。DK=0 表示不启用。DK=n 时，今日权重按公式加权过去 n 天的仓位。 |
| **Neutralization** | 中性化。用户阶段主要是**市值中性化（多空金额平衡）**。选项：None / Market / Sector / Industry / Sub-industry 等。 |
| **Truncation** | 截断，限制极端权重 |
| **Pasteurization** | 巴氏杀菌，处理异常值 |

### DK（Decay）计算公式
- 分母 = n + (n-1) + ... + 1 = n(n+1)/2
- 今天（x_day）的权重系数 = n / 分母
- 昨天（x_day-1）的权重系数 = (n-1) / 分母，以此类推。
- **关键原则**：若 Alpha 中用了 `ts_xxx(..., 10)`，DK 不宜超过 10，否则会引入额外信息，造成"词不达意"。

### Neutralization 计算步骤
1. 在指定分组（market/sector/industry）内计算 Alpha 值的**均值**。
2. 每个股票的 Alpha 值减去该组均值 → 得到有正有负的序列，且**组内求和为 0**。
3. 取绝对值后归一化为权重 → 正数部分合计为 +0.5，负数部分合计为 -0.5，实现**金额上的多空平衡**。

---

## 三、关键指标与术语

| 指标 | 定义 | 阈值/考点 |
|---|---|---|
| **Returns** | 年化收益率 | 过去 5 年（用户）/ 10 年（顾问）回测的平均每年收益 |
| **Sharpe** | 夏普比率 = 每日收益均值 / 每日收益标准差。衡量赚钱稳不稳。 | 参考值：**>1.25** 或 **>1.62**（不同 region/universe 可能不同） |
| **Fitness** | 稳健性指标，类似夏普 | 需 **>1** 才能通过 |
| **Turnover** | 换手率，交易频繁程度 | 越低代表交易频率越低 |
| **Long Count** | 平均每日做多的股票数量（Alpha 值为正的股票数） | 若未做 Neutralization，Long Count 可能接近 Universe 总数 |
| **Short Count** | 平均每日做空的股票数量（Alpha 值为负的股票数） | 若未做 Neutralization，可能为 0 |
| **Coverage** | 数据覆盖度，即该数据字段覆盖了多少只股票 | TOP3000 下 close 的 coverage 约在 3000 左右波动 |
| **Self-correlation** | 与自己历史 Alpha 的盈亏相关性 | 成为顾问后必须 check，用户阶段只检查自己 |

### 样本内 vs 样本外
- **IS（In-Sample）**：样本内，即回测可见的历史数据（用户目前看到约 5 年，2017-2022）。
- **OS（Out-of-Sample）**：样本外，2022 年之后的数据。
- **好 Alpha 的黄金标准**：**OS 表现 ≈ IS 表现**，偏离越小越好（一致性 Consistency）。

---

## 四、FASTEXPR / Operator 大全

### 4.1 横截面运算符（Cross-sectional）
| Operator | 功能 |
|---|---|
| **rank(x)** | 将数据映射到 [0,1]，最小值为 0，最大值为 1，等距分布。消除极端值影响，保留相对排位。 |
| **group_rank(x, group)** | 在指定分组内做 rank |
| **group_zscore(x, group)** | 在组内计算 Z-score（标准化） |
| **group_neutralize(x, group)** | 在组内做中性化（减均值） |
| **sign(x)** | 取符号（正/负） |
| **scale(x)** | 归一化 |

### 4.2 时间序列运算符（Time Series）
| Operator | 功能 |
|---|---|
| **ts_rank(x, n)** | 过去 n 天自己跟自己比，映射到 [0,1] |
| **ts_mean(x, n)** | 过去 n 天均值 |
| **ts_delta(x, n)** | 今天减去第 n 天前的值（环比） |
| **ts_delay(x, n)** | 取过去第 n 天的值 |
| **ts_std(x, n)** | 过去 n 天的标准差 |
| **ts_correlation(x, y, n)** | 过去 n 天 x 与 y 的相关性 |

### 4.3 逻辑与条件运算符
| Operator | 功能 |
|---|---|
| **if_else(condition, true_val, false_val)** | 条件判断 |
| `> < >= <= == !=` | 比较运算 |
| `&&` `||` `!` | 与、或、非 |

### 4.4 Trade_When（非常重要）
- **三个参数**：`(open_condition, alpha_value, close_condition)`
- **判断逻辑**：
  1. 先判断第三个参数（close_condition），若满足 → **直接平仓**，后面的都不看。
  2. 若不满足平仓，再判断第一个参数（open_condition），若满足 → **更新 Alpha 值为第二个参数**。
  3. 若开仓条件也不满足 → **保留上一次的 Alpha 值（previous alpha）**。
- 若第三个参数设为 -1，相当于**关闭平仓功能**（因为条件永远为假）。

### 4.5 Vector 运算符（三维数据专用）
- **Vector Data**：一天内一只股票可能有多条记录（如新闻、分析师数据），是三维数据。
- 使用前必须用 **Vector Operator** 转成二维（Matrix），否则平台报错（brain platform difficulty / take too much resources）。
- 常见：`vector_mean`, `vector_median`, `vector_count`, `vector_std`, `vector_choose_last`（选当天最后一条）。

### 4.6 其他重要运算符
| Operator | 功能 |
|---|---|
| **bucket(x, n)** | 自定义分组，将数据按数值切成 n 个桶，生成 group data field |
| **densify(x)** | 压缩离散的分组编号为连续整数，**使用 group data field 前必须加 densify**，否则可能报资源错误或耗时过长 |

---

## 五、数据字段（Data Fields）

### 5.1 数据层级
- **Data Set（数据集）**：如 `FND6`（Fundamental 6）、`PV`（Price Volume）。相当于"公文包"。
- **Data Field（数据字段）**：如 `close`, `capx`, `liabilities`。是实际写到 Alpha 表达式里的内容。
- **Group Data Field**：分组字段，如 `market`, `sector`, `industry`, `sub_industry`，以及通过 `bucket` 自定义的组。专用于 group operator 的第二个参数。

### 5.2 两大入门数据类型
| 类型 | 更新频率 | 典型字段 |
|---|---|---|
| **Fundamental（基本面）** | 最快**季度更新**（因需审计） | 资产、负债、营收、资本支出(capx)、员工薪酬等 |
| **Price Volume（量价）** | **每日更新**（交易日） | open, close, high, low, vwap, volume, adv20 |

### 5.3 定量探测数据特征的方法（Six Tips）
- 设置 **Neutralization = None**, **Decay = 0**，然后回测。
- 观察 **Long Count / Short Count**：
  - 若 Long Count ≈ Universe 总数，Short Count ≈ 0 → 说明原始值几乎全为正，未做中性化。
- 用 `ts_std(x, n) == 0` 可判断数据在过去 n 天是否有变化 → 推断**更新频率**。
- 常用逻辑：用 `if_else(ts_std(...) == 0, 0, 1)` 统计有变化的股票数，推算 annual update frequency。

---

## 六、回测与提交工作流

### 6.1 用户阶段流程
1. **Write Alpha**（写表达式 + 设置 Settings）
2. **Simulate**（回测）→ 等待进度条（Location）
3. **Check Submission**（检查测试）
4. **Submit**（提交，每天最多拿 2000 分）

### 6.2 并发限制
- **User**：最多同时跑 **3 个** Simulation。
- **Consultant**：最多同时跑 **10 个** Simulation。

### 6.3 代码批量回测要点
- 用 API（`post` 到 simulation endpoint）实现批量提交。
- 通过 `retry` 机制处理 `no location`（进度条未生成）：
  - 可能是表达式错误、排队中、或账号断线。
  - 建议设置失败容忍次数（如 15 次），连续失败后重新登录。
- 建议用 **Log** 记录运行日志，防止断开后不知道跑到哪里。
- 建议把 Alpha 生成与回测执行拆分为**两个 Notebook/脚本**，中间用 CSV 存储。
- 成熟的 Consultant 工作流：写 Alpha → 存入 CSV → Worker 读取并发回测 → 结果写入另一个 CSV/数据库。

### 6.4 Search Space（搜索空间）
- 由模板中各自由度的组合数决定（如 operator 替换、时间参数替换、group data field 替换）。
- 示例：某模板组合出 **57,400+** 个 Alpha；有同学搜到 40 万被认为**过大**。
- 需关注搜索空间大小，过大则回测时间过长。

---

## 七、顾问（Consultant）收入结构与等级

### 7.1 用户阶段积分
- 每提交一个 Alpha：**1500-2000 分**。
- **每天积分上限：2000 分**（无论提交多少个）。
- 达到 **10,000 分** → 收到顾问邀请。

### 7.2 顾问收入组成
| 收入类型 | 说明 |
|---|---|
| **Base Payment（日度底薪）** | Regular Alpha：$1-60/个；Super Alpha：$1-60/个。每天最多交 4 个，日度上限约 **$120**。 |
| **Quarterly Bonus（季度奖金）** | 保底 $100，最高 **$25,000**。需该季度内 **20 个自然日**有提交（不是 20 个 Alpha）。 |
| **Genius Program（天才计划）** | 按评级给保底季度奖金：最高档 **$8,500**，中档 **$2,000**，低档 **$200**。 |
| **Referral（推荐奖励）** | 成功推荐一人成为顾问且对方在 10 个不同自然日提交 Alpha → **$200/人**。 |

### 7.3 新人挑战奖励（仅限首次参加、协议 11/1 后生效）
- 7 个自然日提交 Alpha → **¥500**
- 14 个自然日提交 Alpha → **¥1,000**
- 20 个自然日提交 Alpha → **¥1,700**（¥1,000 + $100 季度保底）
- 截止日期：当年 12/31。

### 7.4 成为顾问流程（三阶段）
1. **提交申请表**（Workday 系统）→ 快速初审（通常 1 天内）。
2. **签署合同**（学生版默认合同；非学生需申请非学生版本）→ 获得 **Conditional Consultant** 权限（可开始累积津贴）。
3. **背景调查**（无犯罪记录、SEC 制裁等）+ 填写银行卡 → 成为 **Full Consultant**。
- 即使 Conditional 阶段，提交 Alpha 已开始累计顾问津贴。

### 7.5 顾问申请填写要点
- 授权表有**两页**，都要填。
- 签名处必须**手写签名**或 iPad/Adobe 签，不能打印名字。
- 身份证只上传**人像面**（或正反面合在一个文件），**不要上传 HEIC 格式**。
- **5 年完整地址历史**，中间不能断。
- 除签名外尽量用英文/拼音，但"完整中文姓名"处必须写**中文**。
- 过去 12 个月内是否是"Work on University"学生 → 在线课程**不算**，选 **No**。
- 如在金融机构任职，可能因利益冲突**不被批准**。
- 全部填完后必须回任务列表再点一次 **Submit**，直到任务栏为空才算完成。

---

## 八、平台规则：该做与不该做

### 8.1 该做的（Good Practice）
- **先理解数据再写 Alpha**：定性（读 description）+ 定量（用 Six Tips 方法探测统计特征）。
- **关注一致性（Consistency）**：OS 与 IS 表现越接近越好。
- **积累模板**：从一个好 idea 抽象出模板，批量替换 data field / operator / group / 时间参数。
- **保持好奇心**：主动搜索、读论文、读论坛帖子（如 Alpha 101、Alpha 灵感启示录）。
- **多尝试不同 Group Data Field**：如 hc（hierarchical clustering）等，可能提升表现。
- **善用 Vector Data**：成为顾问后，可用于降低相关性。

### 8.2 不该做的（禁忌 / Overfitting 红线）
| 行为 | 原因 |
|---|---|
| **不要为了某一年修改 Alpha**（如用 if_else 排除 2018-19 科技股） | 典型的用后视镜开车、Overfitting |
| **Correlation 差一点点就硬改到通过** | 大概率是 Overfitting 或 Underfitting |
| **在一个 Alpha 上花太多时间**（几小时调参数） | 沉默成本导致控制不住 Overfitting |
| **加噪音降低相关性**（如乘 0.03*rank(...)） | 质量极差，虽能提交但拿不到钱 |
| **搜索空间过大（如 40 万+）** | 不现实，回测耗时过长 |
| **不关注样本外表现，只追求能提交** | 会导致组合表现差，季度奖金极低 |

### 8.3 Fitting 的三种状态
- **Underfitting**：还能再改，但过早提交。
- **Overfitting**：调得太细，样本内极好但样本外变差。
- **Ideal Fitting**：样本内与样本外表现基本一致（极少出现）。

---

## 九、关键数字与阈值速查表

| 项目 | 数字 |
|---|---|
| BRAIN 成立年份 | 2007 年 |
| 全球办公室 | 13 个国家/地区，24 个办公室 |
| 员工人数 | 1,000 人 |
| 平台用户 | 100,000+ |
| 顾问人数 | 3,500+ |
| 数据字段总数 | **140,000+** |
| 用户回测历史长度 | **5 年** |
| 顾问回测历史长度 | **10 年** |
| 成为顾问门槛 | **10,000 分** |
| 每日积分上限 | **2,000 分** |
| 每 Alpha 积分 | 1,500-2,000 分 |
| 用户并发回测 | **3 个** |
| 顾问并发回测 | **10 个** |
| 季度奖金最低/最高 | $100 / **$25,000** |
| Genius 保底档位 | $8,500 / $2,000 / $200 |
| 新人挑战 7/14/20 天奖励 | ¥500 / ¥1,000 / ¥1,700 |
| 推荐成功奖励 | $200/人 |
| 季度奖金参评最低提交天数 | **20 个自然日** |
| 顾问日提交上限 | 1-4 个 Alpha |
| Sharpe 常见通过线 | >1.25 或 >1.62（视设置而定） |
| Fitness 通过线 | >1 |
| 标准一年交易日 | 252 天 |
| 一个季度交易日 | 66 天（约） |
| FND6 字段数示例 | 约 574 个可生成 Alpha |
