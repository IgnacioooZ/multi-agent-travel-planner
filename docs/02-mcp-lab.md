# 今天的实践：理解架构并亲手调用 MCP

目标：你能解释谁调度 Agent、谁调用工具；能发现 MCP 工具、查看参数、执行真实沙盒查询、观察错误和核对结果。无需 API Key 即可完成前五步。

## 先分清两个维度

**中心化 / 去中心化**讨论谁管理任务与协调结果；**串行 / 并行**讨论多个任务的执行时序。中心化编排器也能并行派发 worker，去中心化系统也可能有等待依赖。多智能体不等于多线程。

当前 `workflow.solve()` 是 Python 写死顺序的中心化工作流：

```text
Python 编排器 solve()
  1. await logistics.run()   交通与住宿候选
  2. await activities.run()  读取第 1 步结果，生成景点餐饮候选
  3. await planner.run()     读取两份结果与原始工具证据，生成行程
```

LLM 在每个角色内部决定查什么工具；角色顺序由 Python 决定。planner 是结果整合者，没有委派其他 Agent 的工具，所以还不是动态 Supervisor。当前没有 A2A、worker 之间自主发消息或并行执行。`async/await` 允许异步等待，但逐个 await 仍然是串行流程。

以后要改成中心化并行，可以让两个研究角色同时查询，然后让 planner 汇总。但现在 activities 会读取 logistics 的结果，而且官方工具有 `next_page` 会话状态，不能直接把两个调用塞进 `asyncio.gather` 就认为等价：要重新设计依赖、隔离各 worker 的查询会话，并保证全局预算计数正确。

## MCP 在什么位置

```text
DeepSeek 返回工具调用名称与参数
  → Agent.run() / 应用 Host 检查角色权限和预算
  → MCPTools.call() / MCP Client
  → stdio 管道 / JSON-RPC
  → lab.mcp_server / 独立 Python 子进程
  → 官方 ChinaTravelEnvAdapter
  → 官方本地沙盒
  → 结果原路回到 Agent，再提供给模型
```

模型不会直接启动子进程或执行数据库函数，执行工具的是应用。VS Code 在这里是编辑器；实际 MCP Host 是运行 `lab.cli` 的 Python 应用。

本项目使用锁定的 MCP Python SDK 1.x，客户端执行初始化握手、`tools/list`、`tools/call`。本地 stdio 不需要 HTTP 地址或端口。进入 `connect_tools('mcp')` 会启动服务端，退出会关闭会话和子进程；不需要另外开终端手动启动 server。

只运行 `python -m lab.mcp_server` 时进程会等待协议消息，这是正常行为；不能在里面直接输入“帮我查杭州”。服务端 stdout 专用于协议消息，日志写 stderr。

## 第 1 步：发现工具

在项目根目录的 PowerShell 终端执行：

```powershell
.venv\Scripts\python.exe -m lab.cli tools
```

预期看到 18 个工具，来自官方沙盒。这里只看说明；尚未查询旅行数据。

关注：`attractions_select`、`restaurants_select`、`accommodations_select`、`intercity_transport_select`、`goto`。

## 第 2 步：查看参数约定

```powershell
.venv\Scripts\python.exe -m lab.cli tools --name attractions_select
```

查看 `function.parameters` 里面的 `properties` 和 `required`。MCP 原本返回 `inputSchema`，客户端把它适配为模型工具调用使用的 `parameters`。这种协议格式转换不会改变工具的业务功能。

本工具需要 city、key、op、value。比如 key=price、op=le、value=100 表示票价小于等于 100。对字段不熟悉时，先调用 `attractions_keys` 获取真实字段名。

## 第 3 步：真的查询一次

打开 `examples/mcp/attractions.json`，它是调用参数，不是模型提示词：

```json
{"city":"杭州","key":"price","op":"le","value":100}
```

运行：

```powershell
.venv\Scripts\python.exe -m lab.cli call attractions_select --args-file examples/mcp/attractions.json
.venv\Scripts\python.exe -m lab.cli call intercity_transport_select --args-file examples/mcp/trains.json
```

检查 `success`、`data.rows`、`row_count` 和 `returned_rows`。这是真实 benchmark 沙盒数据，不是实时景点/票务信息。默认返回前 10 条，并保留分页信息。

现在把景点参数里的 value 改成 0 再运行，观察免费景点。结束后改回 100。你只修改查询条件，未修改官方数据库或评分器。

## 第 4 步：观察一个可解释的失败

```powershell
.venv\Scripts\python.exe -m lab.cli call attractions_select --args-file examples/mcp/missing-arguments.json
```

这个文件只给了 city，故意缺少必填字段。预期：`success: false`、验证错误信息、命令退出码 1。说明参数检查生效；不是“模型不聪明”。

服务端同时使用 MCP 的 `isError` 标记执行失败；客户端把它转换成统一的业务结果。即使工具结果正文意外写了 success=true，协议层 isError=true 仍然按失败处理。

## 第 5 步：运行 MCP 独立验收

```powershell
.venv\Scripts\python.exe -m lab.cli mcp-check
```

检查：初始化能力、18 个工具及 schema、与直接调用相同的查询结果、参数缺失/类型/枚举错误、未知工具、隐藏标注工具的服务端拒绝，以及失败后继续查询。

记录保存到 `runs/mcp-check/report.json`，含协商协议版本、工具列表、请求参数与结果。它是按 SDK 调用记录的协议步骤，不是原始管道抓包。验收不会请求模型，也不是旅行任务通过率。

## 第 6 步：接入真实 Agent

本项目的 `tools`、`call` 和 `run` 命令现在默认使用 MCP；可显式用 `--transport direct` 做对照。

填写本地 .env 后，再运行：

若只想验证模型与 MCP 的完整链路，可先做小规模连通测试（最多 2 次模型调用、1 次工具调用，会产生 API 费用）：

```powershell
.venv\Scripts\python.exe -m scripts.probe_mcp_model
```

2026-11-05 已实际运行通过，记录在 `runs/20261105-220509-593543-mcp-model-probe/report.json`。这一步只查询交通信息，不是完整任务评测。之后再运行一条完整旅行任务：

```powershell
.venv\Scripts\python.exe -m lab.cli run --mode single --transport mcp --limit 1
.venv\Scripts\python.exe -m lab.cli run --mode multi --transport mcp --limit 1
```

这两条命令会使用 DeepSeek 并产生 API 费用。检查 `trace.jsonl` 中的 `model_request`、`model_response`、`tool_result` 和 `handoff`。真实模型能否选对工具、生成有效行程是下一层评估，不能由 MCP 验收代替。

## 对照代码阅读

1. `lab/cli.py`：把你手动给的参数交给客户端。
2. `lab/tools.py` 的 `connect_tools`：启动子进程、初始化、管理会话生命周期。
3. `MCPTools.list_tools` / `call`：协议客户端；不是工具业务实现。
4. `lab/mcp_server.py` 的 `list_tools` / `call_tool`：声明工具并执行请求。
5. `DirectTools` → 官方 `agent_env/adapter.py` → `agent_env/tools.py`：参数验证、方法分发及沙盒查询。
6. `lab/agent.py`：模型提出调用，应用执行并把结果回传，形成循环。

现在使用一个 MCP server 提供所有沙盒工具，所有角色由同一个应用通过客户端访问；并不是“一个 Agent 必须配一个 MCP server”。MCP 负责工具接入，不负责决定 Agent 的分工，也不等于 A2A。

今天先掌握这些接口。后续你若想亲手写一个工具，可以在开发实验中新增封装，但正式 benchmark 对照应保持官方工具语义与数据一致。

参考：[MCP 工具规范](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)、[ChinaTravel 环境说明](https://github.com/LAMDA-NeSy/ChinaTravel/blob/main/agent_env/README.zh-CN.md)。协议细节以项目锁定的 SDK 与运行时协商版本为准，不混用最新版示例替换本项目代码。
