# 02 零基础学量化_第二课

> 来源: transcripts/02-零基础学量化_第二课_XNjQ1Mjg5Mzk4NA.auc.md

## 要点

- 课程介绍上节课作业情况，讲解阿尔法概念、数据与算子知识，给出做阿尔法的方法论及代码示例，布置课后作业。
- 课程开放 Q&A 选项，课后答疑通过举手方式在问答区留言。
- 上节课作业：Task 1 按示例和代码应能交两个，分开两天交约有 3000 - 4000 分；Task 2 需用心在量化金融语境中完成；Task 3 作业阿尔法是负的 close，常见错误有加 rank、位置和不为 0、漏负号；Task 4 注意保护账号密码，location 报错代表进度条问题，可复制粘贴到平台排查。
- 阿尔法是数学公式和模型，由 operator 与 data 组合，每天算出阿尔法值，经 neutralization 和 normalization 处理。
- 本节课讲 data 与 operator，data 如食材，operator 如厨具。
- 平台上 operator 合集在 learn 界面的 operator 选项，data 在最上面框框的 data 选项，simulate 界面右上角也可搜索 data 和 operator。
- 了解 data 有定性和定量两种方式，常见 data 有基本面数据和量价数据。
- 基本面数据出自资产负债表、损益表和现金流量表，更新频率最快为季度，对公司运营状况有启示作用。
- 量价数据包括开盘价、收盘价、最高价、最低价、成交量加权平均价格（VP）、过去 20 天平均成交量（ADV20），更新频率为交易日每天更新。
- data set 是数据集，data field 是数据字段，只有 data field 可写到平台 simulation 界面。
- 定量了解 data 可通过论坛 sixtips 帖子，用回测方式设置 new chalization 为 none、DK 为 0，查看 long count 和 short count 了解数据特征，引入 coverage 概念。
- 常见 operator 有 rank（保证数据相对位置关系，消除距离信息）、sign（表示符号）、scale（归一化）、TSDelta（做差）、TSDELAY（获取过去第 n 天的值）等。
- operator 分类方式：按运算横纵分有 cosectional operator、time series operator、逻辑 operator；按功能分有 comparison（对比）和 aggregation（整合组合）。
- trade when operator 用于开仓和平仓，有三个参数，先判断平仓条件，再判断开仓条件。
- 做阿尔法的方法论：从基本面数据集拿数据字段除以市值生成财务比例，拓展阿尔法；通过 API 获取数据集 ID 下的数据字段，替换到阿尔法模板生成多个阿尔法并回测。
- 课后作业：参考 101 个阿尔法文章；研究 data field 更新频率并解释理由，附上回测结果；解释 trade when operator 逻辑，用 if else 等价实现；用 get data field 批量生成阿尔法并回测 20 次以上；获得 10000 分并截图 challenge school。

## QA

### Q: 上节课作业提交后能得多少分？
A: 按示例和代码，分开两天交约有 3000 - 4000 分。若同一天提交，不管提交多少个，最多 2000 分。

### Q: 上节课作业 3 有哪些常见错误？
A: 常见错误有加 rank、位置和不为 0、漏负号。作业阿尔法是负的 close，前面加负号即可算出真正的阿尔法值。

### Q: 作业 4 中 location 报错是什么意思？
A: location 代表平台上的进度条，报错意味着进度条不能跑，即平台报错。可将阿尔法复制粘贴到平台，排查错误。

### Q: 什么是阿尔法？
A: 阿尔法是一个数学公式和模型，由 operator 与 data 组合，每天算出阿尔法值，经 neutralization 和 normalization 处理。

### Q: 平台上在哪里可以找到 operator 和 data？
A: operator 合集在平台 learn 界面的 operator 选项；data 在最上面框框的 data 选项，simulate 界面右上角也可搜索。

### Q: 常见的 data 有哪些？
A: 常见 data 有基本面数据和量价数据。基本面数据出自三张财务报表，更新频率最快为季度；量价数据包括开盘价、收盘价等，交易日每天更新。

### Q: data set 和 data field 有什么区别？
A: data set 是数据集，像公文包；data field 是数据字段，装在数据集里，只有 data field 可写到平台 simulation 界面。

### Q: 如何定量了解 data？
A: 可通过论坛 sixtips 帖子，用回测方式，设置 new chalization 为 none、DK 为 0，查看 long count 和 short count 了解数据特征，引入 coverage 概念。

### Q: rank operator 有什么作用？
A: rank operator 保证数据之间的相对位置关系，但消除了位置的距离，对极端值不敏感，只保留相对排位。

### Q: trade when operator 的逻辑是什么？
A: 它有三个参数，先判断第三个参数的平仓条件，满足则直接平仓；若不平仓，再判断第一个参数的开仓条件，满足则更新阿尔法值，不满足则保留上一次的值。

### Q: 如何做阿尔法？
A: 从基本面数据集拿数据字段除以市值生成财务比例，拓展阿尔法；通过 API 获取数据集 ID 下的数据字段，替换到阿尔法模板生成多个阿尔法并回测。

### Q: 课后作业有哪些？
A: 参考 101 个阿尔法文章；研究 data field 更新频率并解释理由，附上回测结果；解释 trade when operator 逻辑，用 if else 等价实现；用 get data field 批量生成阿尔法并回测 20 次以上；获得 10000 分并截图 challenge school。

### Q: 提交阿尔法时一直转圈不回复怎么办？
A: 通常转圈 10 分钟内正常，若超过 10 分钟，不要一直点，等转圈完若显示超时或灯再亮，可再点一次。若还不行，建议换浏览器。

### Q: 如何理解 long count 和 short count？
A: long 表示做多，short 表示做空。若阿尔法位置为正数则做多，long count 增加；为负数则做空，short count 增加，一年的 long count 和 short count 是每天的平均值。

### Q: 用代码提交阿尔法回测时间长怎么办？
A: 要挂着程序，但不用一直坐在电脑前等。成熟的研究员会把程序挂到云电脑或云服务器上。

### Q: 提交阿尔法后没有反馈怎么办？
A: 点 check 可能需 3 - 5 分钟，check 完再点 submit，成功会跳出“submit successful”，失败会跳出“fail”，反馈一闪而过。若超时，可换浏览器。

### Q: 定量分析数据时 settings 要设置哪些？
A: new chalization 要设置成 none，DK 要设置成 0。

### Q: 测 frequency 用的 operator 是什么？
A: 不用特意记，在论坛 sixtips 帖子里有。

### Q: competitions 里只有排名没有得分怎么看？
A: 点完 commitation 第一个，上面第一行 talent，点 talent 这个地方确认即可看到得分。

### Q: 为达到 10000 分每天要提交几个阿尔法？
A: 每天交一个，连续最少四天，最多五天就能拿到 10000 分。注意 submission dates，从当天开始提交。
