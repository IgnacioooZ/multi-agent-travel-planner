# 输出契约、计划语义与评分器错误的根因

本次调查对象是关闭累计 token 限制后的 10 条试运行。不是所有失败都属于 schema，也不是 MCP 已查到数据就意味着 Planner 会正确使用数据。

## 1. 已复现的因果链

### 生成端没有真正执行 schema 验收

旧 `workflow.solve()` 只把 `output_schema()` 放入提示词，`Agent.run()` 看到没有 `tool_calls` 就交接；`parse_plan()` 仅执行 JSON 解析和顶层对象检查。API 请求没有严格结构化输出约束，程序也没有做生成后 schema 检查。因此合法 JSON、合格 schema、正确计划被混为一种“completed”。

9 份已保存计划中，两份（easy `e20241028160248698752`、medium `e20241028160842228543`）的往返火车条目均缺少必需的 `start`/`end`，却被保存成完成状态。这是本项目的实现遗漏。

### 官方 schema 不等于完整业务契约

官方 schema 在条件分支要求火车/航班有车站/机场字段，但 `properties` 没有进一步描述字段语义；出租车 `cars` 未定义，若干票数和房数也未强制要求。评分器却使用这些字段计算费用。

旧计划中可直接复现的问题：

- 将交通费计入活动 `cost`，导致门票 `price=0` 而活动 `cost>0`。
- 把前往景点的交通写成一个景点活动，再写一次正式游览，产生重复景点。
- 将多个 `goto` 路线拼接进同一活动；官方语义是一次进入该活动的路线。
- 交通到达时间晚于活动开始，或路线终点与活动位置不一致。
- 缺少出租车车数、地铁票数、住宿房数或房型。

这些不是 JSON 语法错误；即使 schema 通过，依然可能发生。公开检查重放发现 9 份计划都有可定位的问题（每份最多列出 20 条，schema 错误优先返回）。

### 官方评分器有可复现的异常

固定上游版本 `f445e0011f42594fcc29b8c752ece06ded9a8218` 的 `chinatravel/symbol_verification/commonsense_constraint.py`：

- 第 836 行创建列 `Inccorrect cost information of Inner-City Transport`。
- 第 1029 行等错误分支向 `Incorrect cost information of Inner-City Transport` 赋值，多创建一列。
- 第 1032 行等分支给整行赋三个值，此时已有四列，抛出 `ValueError: Must have equal len keys and value when setting with an iterable`。
- 上层捕获异常，常识检查提前退出，后续检查没有执行。原报告中的常识微观分数不能据此当成完整诊断。

5 份旧计划可稳定触发该问题。`scripts/apply_upstream_fixes.py` 仅统一这一个列名，保留规则、数据与计划。bootstrap 自动应用；`lab/evaluate.py` 记录是否应用、源码 SHA256 与异常计数。修复后的 9 份重评分中异常 0 份、完整通过仍为 0 份：评分器有 bug，但不能据此说原计划正确。

原始异常栈：`runs/20261107-170007-pilot10-d9132d21/scorer_exceptions.json`。保留原评分的重放结果：同目录 `diagnosis/plan_audit.json`。

### 交接成功，不代表规划改动之后证据仍然成立

第二次真实复测提供了直接证据：Activities 调用 `attractions_id_is_open(city='杭州', id=3, time='10:00')` 得到 True；`attractions_select` 原始记录中西湖游船开放时间是 08:00–17:00。Planner 却把最终游览排到 07:37–10:50。MCP 没丢数据，原始记录也确实在 Planner 上下文中；是 Planner 改了时间，没有重新核对事实条件。

为此，提交检查现在还读取交接和 Planner 本轮查询中的结构化工具行，按城市、类别、实体名关联最终活动，核对已知营业时间和价格。不把 `is_open(10:00)=True` 推广为任何时刻都开放。尚未实现对所有工具结果的全面证明：只在存在明确来源的记录时核对，缺少证据的项目不能据此宣称已核实。

### 单次输出截断是另一个独立问题

human `h20241029143451793119` 最后一次 Planner 返回 `finish_reason=length`，输出达 4096 tokens，JSON 未闭合。关闭累计 token 阈值不会改变单次输出长度。现在识别截断并要求压缩后重新提交，最多两次；仍不能完成时明确失败。没有宣称该长行程问题已完全解决，4096 上限仍然存在。

## 2. 实现变化与边界

- `lab/validation.py`：解析 → 官方 Draft7 schema → 基本数量、费用、路线、时间、重复景点与公开用餐时段 → 已知工具记录中的营业时间/价格检查。
- `lab/agent.py`：最终提交不通过时写入 `validation_failed` 日志，向同一 Agent 返回具体错误；最多两次修正，并受原轮次和共享调用预算约束。不能修正则 `InvalidPlan`，不能假报交接成功。
- `lab/workflow.py`：明确字段含义、费用归属、完整单次路线、车站名称、数量及用餐要求；single 与 multi 的 Planner 使用同一核验规则。
- `scripts/apply_upstream_fixes.py` / `lab/evaluate.py`：修复评分器列名并记录版本信息。

核验不导入私有任务、隐藏约束或离线评分器，也不自动替模型修改答案。不保证全部事实、未查询的营业时间、跨日路线和用户需求正确。两研究角色的 `content` 仍未强制结构化；上下文仍较大，这是后续工作。

## 3. 真实复测与验证

同一开发任务 `e20241028160248698752`，multi + MCP，DeepSeek，累计 token 不设限，其他预算保留。未将任务隐藏约束加入上下文。

第一次修复复测：`runs/20261107-172151-241244-easy-multi-4895c115/`。

- Planner 首次输出缺两处 taxi `cars`；检查准确返回两条错误，下一次输出补齐。
- 12 次模型调用、28 次工具调用，输入 188488、输出 9500，合计 197988 tokens，72.51 秒。
- schema 通过、5/5 硬约束通过；常识 26/27 项通过，完整通过仍为 false。
- 唯一剩余常识错误：晚餐 16:37–17:00，没有覆盖 benchmark 的晚餐时段。随后加入公开餐次时段检查及返程冲突说明；官方判定是与午餐 11:00–14:00 / 晚餐 17:00–20:00 有正时长交集，检查不读取任务专属标注。

第二次修复复测：`runs/20261107-172438-513323-easy-multi-e66cf346/`。

- 15 次模型调用、23 次工具调用，输入 233466、输出 8592，合计 242058 tokens，69.31 秒。
- 一轮反馈修复两处 taxi `cars`；schema 与 5/5 硬约束通过，餐次检查也通过。
- 常识仍为 26/27 项通过，唯一错误变成景点开放时间：西湖游船 07:37 开始，而工具记录 08:00 才开放。完整通过仍为 false。由此增加上述工具记录核验。

第三次（最终版本）复测：`runs/20261107-172800-289156-easy-multi-4d3d22af/`。

- **schema、常识约束、硬约束与 all_pass 全部为 true**；评分器异常 false。
- 13 次模型调用、34 次工具调用，输入 229198、输出 9660，合计 238858 tokens，67.68 秒。
- 首次提交被拦截：三处出租车缺 `cars`、返程活动与上一活动重叠、到站晚于返程开始。反馈修正后完整通过；所有反馈和工具查询保存在 trace。
- 34 项自动化测试通过，含真实 MCP 集成、提交修正、截断拒绝、费用/时间/路线错误、用餐边界、工具营业时间/价格及评分器异常回归。
- 独立重放第二次结果，使用其公开交接内容与 Planner 工具记录，确认新增检查能捕获西湖游船 07:37 早于 08:00 开门的问题，记录为该任务目录下 `public_validation_replay.json`。

本次三轮真实调试合计 **678904 tokens、40 次模型调用、85 次工具调用**，全部保留，不只展示最好的一轮。最终通过的是一条开发任务的一次运行，未重新运行原 10 条，也未做 single 对照。不能据此宣称泛化成功率或多智能体优势。新旧版本同时改了提示词和验证机制，尚未做消融来分离贡献。

各新运行目录包含 `source_snapshot/` 和 `source_hashes.json`，原计划与评分不覆盖。原始 9 份计划的离线重评分不会产生模型费用。

复现命令：

```powershell
.venv\Scripts\python.exe scripts/apply_upstream_fixes.py
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/audit_plans.py runs/20261107-170007-pilot10-d9132d21
.venv\Scripts\python.exe -m lab.cli run --mode multi --transport mcp --uid e20241028160248698752
.venv\Scripts\python.exe -m lab.evaluate runs/替换为新运行目录
```

前 3 条不调用模型，后两条中只有 `run` 产生模型费用。原始计划、原评分和新运行分别保留。
