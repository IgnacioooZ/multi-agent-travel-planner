# multi 优化方向 A+C —— 修复两条已知失败 + 提升复杂任务通过率

> 2026-11-08 | 模型 deepseek-chat (temp 0.0)，MCP 传输
> 方向 A = 修复 medium(预算/时间联合) + human(重复餐厅)；方向 C = 扩展 medium/human 对照

## 背景：10 条开发集（4 easy + 3 medium + 3 human，各 split 前 N 条）

multi 冻结基线 = 8/10（easy 4/4，medium 2/3，human 2/3）。两条失败：
1. medium `e20241028160848776495`（4 人 2 天 广州→杭州 火车 5600 元，开两间双床房）—— 预算/时间联合未收敛。
2. human `h20241029143451793119`（南京→重庆 4 天）—— 餐厅被误判为景点、住宿排到中午、返程班次太晚。

## 本轮改动（按因果链）

### 1. multi 规划角色用完共享预算（lab/workflow.py）
- `planner_rounds = 24 if single else max(8, max_model_calls - usage.model_calls)`。
- 之前 logistics(6)+activities(6)+planner(12)=24，但研究角色常提前结束（logistics 只用了 3 次），剩下的预算被浪费，planner 只拿到 12 轮。
- 现在 planner 拿走研究角色剩下的全部预算（实测 3+6 → planner 15 轮），不超 24 的共享上限。

### 2. 提交窗口 rounds-4 → rounds-6（lab/agent.py）
- 复杂 4 天任务需要 >4 次 finalize 才能收敛；提交阶段从最后 4 轮扩到 6 轮，多给两次改错机会。

### 3. 直接输出 JSON 的修正消息不再自相矛盾（lab/agent.py）
- 原消息一边说 "Use finalize_plan" 一边说 "重新输出完整紧凑 JSON"，模型被绕晕。
- 现在统一为 "请调用 finalize_plan，不要直接输出 JSON"。
- 有界修正次数 2 → 6，避免一次 API 超时后几条畸形 JSON 就把 run 判死（InvalidPlan）。

### 4. 过夜列车检查只针对去程（lab/validation.py）
- 官方评分器 `Is_time_correct` 明确放过 train/airplane 的次日到达（`# 可能出现次日到达`）。
- 旧检查把**所有**跨午夜列车都当错误，导致模型回避便宜的过夜返程 K511(419.25) 而改选更贵的同天返程。
- 现在只标记去程过夜（到达次日 → 当天无夜、无法住店、返程无从安排）；返程作为最后一项不报错。

### 5. 预算提示标注「次日达」（lab/plan_tool.py）
- 最便宜城际班次列表里给过夜班次加 `次日达` 后缀，帮模型区分 K512(次日达，不适合去程) 与 D3124(当日到)。

### 6. 实体类别提示（lab/plan_tool.py table + lab/workflow.py 提示词）
- `table()` 跨类目提示：名字在其它类目命中时提示 "(it is a accommodation, not a restaurant)"。
- PLANNER 提示词新增：酒店名含「酒店/宾馆/民宿/公寓」属于 accommodations_select，不要填成餐厅；餐厅/景点同理用对应 select 确认。

## 验证结果：10 条开发自检集（最终代码）

| 划分 | single | multi | 差异任务 |
|---|---|---|---|
| easy | 4/4 | 4/4 | — |
| medium | 2/3 | **3/3** | `e20241028160848776495`（预算/时间联合）single 失败、multi 通过 |
| human | 3/3 | 3/3 | — |
| **合计** | **9/10** | **10/10** | |

- 冻结基线 multi = 8/10，改后 multi = **10/10**（预算任务 + 两条 human 全部转 PASS）。
- 关键差异点：medium 预算任务 `e20241028160848776495`（4人2天 广州→杭州 火车 5600，开两间双床房）—— multi 的 logistics/activities 分工能并行比较城际班次与住宿价格，找到 D3124(628.88)+K511(419.25)+游孑酒店(168×2) 的可选组合；single 模式下 planner 独自 24 轮仍未能收敛到预算内。这是多 agent 协作价值的最直接证据。

## 正式 dev 评测（进行中）
- 3 划分 × single/multi × 3 次，每轮 30 条（`--subset all --limit 30`，即各 split 前 30 条，single/multi 同批任务对照）。
- 结果增量写入 `/tmp/eval_dev_full_results.txt`，跑完回填下方。

## 事故记录：VPN 掉线挂死 + 超时兜底修复（2026-11-09 凌晨）
- 首次启动后，easy-single 第 20 条在 00:45 发出一次 model 请求后永久挂起（进程 CPU 仅 2.9s，空等 8h）。
- 根因：代理 VPN 掉线导致 TCP 半开，openai SDK 的 `timeout=120` 未触发（半开连接无 FIN/RST，读超时未按预期抛出）。
- 修复（`lab/agent.py`）：`DeepSeekModel.complete()` / `provider_output_limit()` 的 `create()`/`models.list()` 外包 `asyncio.wait_for(..., timeout=settings.timeout_seconds+60)` 作硬上限；Agent 重试分支同时捕获 `TimeoutError`。44 tests 全过。
- 评测脚本 `/tmp/eval_dev_full.sh` 每轮加 2h 看门狗（`kill -9`），轮次超时记 `RUN_FAILED` 后继续，杜绝无限卡住。

## 结论待写
（等 30 条正式评测出数后回填方差 + 显著性。）
