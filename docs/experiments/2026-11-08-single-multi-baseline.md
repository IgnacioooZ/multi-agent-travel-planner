# single / multi 基线（单任务，Mac 环境首次复现）

> 2026-11-08 | 环境：macOS（darwin 24.5.0），Python 3.12.11，uv 0.13.7
> 代码提交：`5292679 Finalize MCP plan grounding and evaluation workflow; refresh README`
> 数据：ChinaTravel easy 300 / medium 150 / human 154，sandbox 30 CSV（bootstrap 恢复，sha256 校验通过）

## 任务

- uid：`e20241028160248698752`（easy，固定开发集）
- request：`当前位置上海。我一个人想去杭州玩一天，预算1500人民币，请给我一个旅行规划。`

## 配置

- 模型：`deepseek-chat`（服务端 `deepseek-flash`），`temperature 0.0`
- 传输：MCP（`--transport mcp`）
- 预算：24 模型请求 / 60 工具调用，累计 token / 输出上限均不设限

## 结果

| 指标 | single | multi |
|---|---|---|
| 完整通过（schema+常识+硬约束） | ✅ 1.0 | ✅ 1.0 |
| 延迟 (s) | 14.10 | 43.07 |
| 模型调用 | 7 | 12 |
| 工具调用 | 13 | 31 |
| 输入 tokens | 70,498 | 191,498 |
| 输出 tokens | 2,275 | 8,626 |
| **总 tokens** | **72,773** | **200,124** |
| grounding_queries | 13 | 26 |
| 连接重试 | 0 | 0 |
| 评分器异常 | 0 | 0 |

运行目录：
- multi：`runs/20261108-161630-304042-easy-multi-7beca880`
- single：`runs/20261108-161738-069472-easy-single-2f2c66ed`

## 初步观察

1. **正确率相同**：single 与 multi 在该 easy 任务上都完整通过，无评分器异常、无 token 截断。
2. **single 显著更省**：single 用时 14.1s vs multi 43.1s（约 1/3），总 tokens 72.8K vs 200.1K（约 1/2.75），模型调用 7 vs 12，工具调用 13 vs 31。
3. 说明在**这条简单任务**上，三角色研究（Logistics + Activities）产生的中间推理与交接并没有换来正确率提升，反而带来约 2.75 倍 token 与 3 倍耗时开销。

## 局限（重要）

- 这是**单条 easy 任务、单次运行**，不能代表 multi 在 medium / human（多意图、依赖/条件预订、长对话）上的表现。
- 单次运行存在采样波动；需重复运行并扩展到更多任务（尤其 medium/human）才能下结论。
- 与 `docs/experiments/latest-results.json` 的 8/10 是不同口径：那是 4 easy + 3 medium + 3 human 的 multi 开发集结果，本条只是其中 1 条 easy 的 single/multi 配对。
