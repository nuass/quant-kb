# 05 Super Alpha入门.merged

> 来源: transcripts/05-Super-Alpha入门.merged.md

## 要点

- 本次会议是研究小组扩大会议，先分享 Super Alpha，后进行研究小组颁奖，研究小组同学每两周评奖，奖金 300 元左右。
- 每日 Base Pay 由 RIQ 阿尔法和 Super Alpha 组成，最多获 120 美元，二者分开计算。
- 约 50% 的参与者拥有 Super Alpha 权限，竞争难度小于普通阿尔法。
- 提交 Super Alpha 可增加 Base Pay，建议有权限者积极提交。
- 优秀顾问的 self correlation 尽量控制在 0.6 以下；value factor 高的同学，提交 4 个阿尔法收入增加最多。
- 提交阿尔法时，建议选择带有主题的，Multiplayer 在 1.2 以下的基本无增益。
- 拥有 100 个阿尔法后才有 Super Alpha 权限，因阿尔法数量少组合无意义且结果不稳定。
- Super Alpha 提交时，turn over 需在 40% 以下，且必须写 description。
- Super Alpha 卡槽有 3 个，有 API，可在 Alpha creation engine 界面下载 ACE templates 查看。
- Super Alpha 选择数量限制为 10 - 500 个，数量越多计算越慢，可能超时，可先小数量测试。
- selection handling 用于处理选择表达式的结果，处理 0 和 none 的情况，最终关注结果正负。
- 选择阿尔法时，常用 selection handling 和 selection limit，500 个阿尔法的 operator 总和不能超过 8000 个。
- 可从 turnover、Decay、delay 等多个角度选择阿尔法，还可根据 universe size、self coalition 等指标筛选。
- 成为 grandmaster 后，可根据作者的 product、Alphayeah the rate per quarter 等筛选阿尔法，可通过加负号、使用 operator 或 rank 选择不同排名的阿尔法。

## QA

### Q: 研究小组的颁奖规则是什么？
A: 研究小组同学每两周评一次奖，设置了多种有趣奖项，符合奖项的同学可获得约 300 元奖金。

### Q: 每日 Base Pay 由什么组成？
A: 每日 Base Pay 由 RIQ 阿尔法和 Super Alpha 组成，二者分开计算，一天最多可获 120 美元。

### Q: 拥有 Super Alpha 权限的人数比例是多少？
A: 约 50% 的参与者拥有 Super Alpha 权限，竞争难度小于普通阿尔法。

### Q: 如何增加 Base Pay？
A: 可通过提交 Super Alpha、提交 correlation 低的阿尔法、提交与主题相关的阿尔法来增加 Base Pay。

### Q: 优秀顾问的 self correlation 应控制在什么范围？
A: 优秀顾问的 self correlation 尽量控制在 0.6 以下。

### Q: value factor 高的同学提交几个阿尔法收入增加最多？
A: value factor 高的同学，提交 4 个阿尔法时，收入增加一般最高。

### Q: 提交阿尔法时对 Multiplayer 有什么要求？
A: 提交阿尔法时，建议选择带有主题的，Multiplayer 在 1.2 以下的基本无增益。

### Q: 获得 Super Alpha 权限的条件是什么？
A: 拥有 100 个阿尔法后才有 Super Alpha 权限，因为阿尔法数量少组合无意义且结果不稳定。

### Q: Super Alpha 提交有哪些特殊要求？
A: Super Alpha 提交时，turn over 需在 40% 以下，且必须写 description，否则无法提交。

### Q: Super Alpha 有几个卡槽？API 在哪里查看？
A: Super Alpha 卡槽有 3 个，其 API 可在 Alpha creation engine 界面下载 ACE templates 查看。

### Q: Super Alpha 选择数量有什么限制？
A: Super Alpha 选择数量限制为 10 - 500 个，数量越多计算越慢，可能超时，可先小数量测试。

### Q: selection handling 是什么意思？
A: selection handling 用于处理选择表达式的结果，处理 0 和 none 的情况，最终关注结果正负，决定是否选择阿尔法。

### Q: 选择阿尔法时常用的设置有哪些？
A: 选择阿尔法时，常用 selection handling 和 selection limit，同时 500 个阿尔法的 operator 总和不能超过 8000 个。

### Q: 可以从哪些角度选择阿尔法？
A: 可从 turnover、Decay、delay 等多个角度选择阿尔法，还可根据 universe size、self coalition 等指标筛选。

### Q: 成为 grandmaster 后如何筛选阿尔法？
A: 成为 grandmaster 后，可根据作者的 product、Alphayeah the rate per quarter 等筛选阿尔法，可通过加负号、使用 operator 或 rank 选择不同排名的阿尔法。
