# 移除本地 token 限制后的 10 条完整复测

本轮先完成全部运行和评分，之后再逐条诊断。运行中没有修改工具、提示词、提交检查或评分规则；没有继续修复业务逻辑。

## 配置与核对

- 累计 token 上限和本地上下文字符数上限均为 None。
- 单次输出不再使用旧 4096 上限，也不省略参数后落入服务端默认值；程序从 `/models` 读取最大输出长度。本轮每次请求均为 393216，单次实际输出最高 5765 tokens，finish_reason=length 次数为 0。
- DeepSeek 仍有服务自身的长度边界，无法提供数学意义的无限单次输出。依据：[模型元数据](https://api-docs.deepseek.com/api/list-models/)、[请求参数](https://api-docs.deepseek.com/api/create-chat-completion/)。
- 模型调用 24、工具调用 60、角色轮次及最多两次提交反馈保持原样。本轮被拒绝的四条均为计划校验失败；没有任务因 token 截断停止。
- 36 项测试通过。生成源码、数据与评分器哈希运行前后相同，调用数与 token 用量核对 trace。
- README 的架构章节、交接代码、角色流程图和并行结构方案已删除。

## 结果

十条全部运行并评分：easy 1/4、medium 0/3、human 0/3，合计 **1/10 完整通过**；评分器异常 0。6 条保存正式 plan.json，4 条未通过提交检查，但最后的候选均为可解析 JSON，已导出 candidate_plan.json。十条均有可查看的计划文件。

4 份被拒绝候选另做离线诊断评分，也均未完整通过；没有因此替换原结果或提高成功率。所有 human 都已走到 Planner，区别于上一轮两条在 Activities 截断。

本轮 157 次模型调用、369 次实际工具调用，输入 3475792、输出 127655，合计 **3603447 tokens**。这比上一轮更费 token，成绩也更低；解除长度限制解决的是截断，未解决计划可靠性。每条仅一次，不能据此断言降低或提高上限对准确性的稳定影响。

## 每条计划与失败分析

### easy — e20241028160248698752

状态：候选未通过提交检查。返程火车 17:53 发车，计划却 18:39 才到杭州东站；提交检查与官方时间检查均拒绝。

[查看计划](../../runs/20261107-175009-pilot10-7103dc6f/easy/e20241028160248698752/candidate_plan.json)。原始输出、提交错误和工具对照详见同目录 `trace.jsonl`、`case_diagnostics.json`（失败任务）以及 `evaluation.json`；候选的另行评分为 `candidate_evaluation.json`。

### easy — e20241028160251109186

状态：候选未通过提交检查。返程火车 18:21 发车，路线 18:46 才到深圳站；提交检查与官方时间检查均拒绝。

[查看计划](../../runs/20261107-175009-pilot10-7103dc6f/easy/e20241028160251109186/candidate_plan.json)。原始输出、提交错误和工具对照详见同目录 `trace.jsonl`、`case_diagnostics.json`（失败任务）以及 `evaluation.json`；候选的另行评分为 `candidate_evaluation.json`。

### easy — e20241028160253742452

状态：完整通过。完整通过，无失败项。

[查看计划](../../runs/20261107-175009-pilot10-7103dc6f/easy/e20241028160253742452/plan.json)。原始输出、提交错误和工具对照详见同目录 `trace.jsonl`、`case_diagnostics.json`（失败任务）以及 `evaluation.json`；候选的另行评分为 `candidate_evaluation.json`。

### easy — e20241028160255878579

状态：提交后评分未通过。南京夫子庙步行街→永和园酒楼，计划填 5 分钟、0.5km；工具复核为 10 分钟、约 0.8581km。原有提交检查没有验证全部路线事实。

[查看计划](../../runs/20261107-175009-pilot10-7103dc6f/easy/e20241028160255878579/plan.json)。原始输出、提交错误和工具对照详见同目录 `trace.jsonl`、`case_diagnostics.json`（失败任务）以及 `evaluation.json`；候选的另行评分为 `candidate_evaluation.json`。

### medium — e20241028160842228543

状态：候选未通过提交检查。第三天返程北京南站 08:00 发车，却 13:50 才到站；官方还报告跨活动/跨日位置衔接问题。

[查看计划](../../runs/20261107-175009-pilot10-7103dc6f/medium/e20241028160842228543/candidate_plan.json)。原始输出、提交错误和工具对照详见同目录 `trace.jsonl`、`case_diagnostics.json`（失败任务）以及 `evaluation.json`；候选的另行评分为 `candidate_evaluation.json`。

### medium — e20241028160845920703

状态：提交后评分未通过。宜致酒店单价记录 329 元；计划首条填 329，后续三个住宿条目填 0。官方按每个住宿条目核对真实单价，失败。

[查看计划](../../runs/20261107-175009-pilot10-7103dc6f/medium/e20241028160845920703/plan.json)。原始输出、提交错误和工具对照详见同目录 `trace.jsonl`、`case_diagnostics.json`（失败任务）以及 `evaluation.json`；候选的另行评分为 `candidate_evaluation.json`。

### medium — e20241028160848776495

状态：提交后评分未通过。杭州火车东站亚朵酒店单价记录 412 元；计划后续住宿条目填 0；另有隐藏硬约束 logic_py_2 不通过，索引保存在 evaluation.json。

[查看计划](../../runs/20261107-175009-pilot10-7103dc6f/medium/e20241028160848776495/plan.json)。原始输出、提交错误和工具对照详见同目录 `trace.jsonl`、`case_diagnostics.json`（失败任务）以及 `evaluation.json`；候选的另行评分为 `candidate_evaluation.json`。

### human — h20241029143447759844

状态：提交后评分未通过。嘉宝酒店单价记录 277 元；计划首条填 277，后续四个住宿条目填 0，触发真实价格不一致。

[查看计划](../../runs/20261107-175009-pilot10-7103dc6f/human/h20241029143447759844/plan.json)。原始输出、提交错误和工具对照详见同目录 `trace.jsonl`、`case_diagnostics.json`（失败任务）以及 `evaluation.json`；候选的另行评分为 `candidate_evaluation.json`。

### human — h20241029143450090032

状态：提交后评分未通过。路线字段与工具不符：如到重庆机场填 40 分钟/70 元/20km，复核为 27 分钟/77.61 元/18.42km。另有一次 goto 参数 JSON 解析失败，未执行工具。

[查看计划](../../runs/20261107-175009-pilot10-7103dc6f/human/h20241029143450090032/plan.json)。原始输出、提交错误和工具对照详见同目录 `trace.jsonl`、`case_diagnostics.json`（失败任务）以及 `evaluation.json`；候选的另行评分为 `candidate_evaluation.json`。

### human — h20241029143451793119

状态：候选未通过提交检查。缺少多段 taxi 的 cars；返程出租车填 price=cost=distance=0，与复核 103.17 元、24.1km 不符。首段南京交通被官方交通检查按目标城市重庆查询，诊断中单独保留这一口径问题，不能把该段查询失败完全归因于模型；其余数量和费用错误仍独立成立。

[查看计划](../../runs/20261107-175009-pilot10-7103dc6f/human/h20241029143451793119/candidate_plan.json)。原始输出、提交错误和工具对照详见同目录 `trace.jsonl`、`case_diagnostics.json`（失败任务）以及 `evaluation.json`；候选的另行评分为 `candidate_evaluation.json`。

## 复查产物

本地实验根目录为 `runs/20261107-175009-pilot10-7103dc6f/`：`manifest.json` 冻结配置和 UID，`canonical_results.json` 汇总正式成绩，`case_analysis.json` 保存逐条计划路径、具体错误、工具错误及输出上限证据。

离线导出/诊断脚本为 `scripts/inspect_pilot.py`，不会请求模型，也不会改写正式计划评分。分析发现的酒店零单价、交通事实改写、返程时间冲突及官方首段城市口径问题，本轮只记录，未进一步修改。
