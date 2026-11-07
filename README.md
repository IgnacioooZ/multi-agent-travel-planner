# Travel Planner

基于 ChinaTravel benchmark 的旅行规划系统，使用 DeepSeek、MCP 和官方沙盒工具生成行程，支持单智能体与三个角色协作，并由独立评分器评估。

## 1. 功能与模块

### Benchmark 与数据

- [ChinaTravel](https://github.com/LAMDA-NeSy/ChinaTravel)：easy 300、medium 150、human 154，共 604 条中文旅行任务。
- Agent 只接收公开的 `uid` 和 `request`；隐藏约束仅由离线评分器使用。
- `data/splits.json` 固定 easy 的本地开发集 10 条、留出集 20 条，属于项目划分，不是官方排行榜划分。
- `scripts/bootstrap.py` 恢复固定版本代码与数据；`benchmark.lock.json`、`uv.lock` 和 `data/manifest.json` 记录版本、依赖与数据来源。

### CLI 与模型客户端

- `lab/cli.py`：选择任务、单/多智能体运行、手动查询工具与保存结果。`main()` 选择命令，`run()` 管理批次，`run_task()` 执行任务。
- `lab/agent.py`：DeepSeek 客户端、Tool Calling 循环、调用计数与日志。
- 默认模型 `deepseek-chat`。本地不设累计 token 或上下文字符数上限；单次输出自动读取服务公布的最大长度，服务自身的容量边界仍然存在。
- 每条任务共享最多 24 次模型请求、60 次工具调用；连接异常最多显式重试一次，计入请求数。

### Agent 角色

角色定义与调度位于 `lab/workflow.py`。当前通过 Python 按顺序交接回答及工具证据，各角色拥有自己的消息历史。

- **Logistics**：交通与住宿研究；使用 `accommodations_*`、`intercity_transport_select`、`poi_lat_lon_search`、`goto`、`next_page`，最多 6 次模型请求。
- **Activities**：景点与餐饮研究；使用 `attractions_*`、`restaurants_*`、`poi_lat_lon_search`、`goto`、`next_page`，最多 6 次模型请求。
- **Planner**：整合需求与研究结果；使用全部工具，最多 12 次模型请求，最后四轮进入提交阶段。
- **single 模式**：跳过研究角色，由 Planner 提示词和全部工具直接完成任务，最多 24 次模型请求。

角色共用当前任务的模型客户端、工具会话与用量计数。推理通过 DeepSeek API 完成，本地运行 Python 和沙盒，不需要独立 GPU。

### MCP 与工具

- **MCP Client**：`lab/tools.py` 中的 `MCPTools`，初始化会话、发现工具并发送调用请求。
- **MCP Server**：`lab/mcp_server.py`，通过本地 stdio 子进程提供工具，任务运行时自动启动并清理。
- **Direct**：同文件的 `DirectTools`，直接调用相同沙盒，供调试与对照。

共 19 个工具：18 个官方查询工具及 1 个本地提交工具。

- 景点：`attractions_keys`、`attractions_select`、`attractions_id_is_open`、`attractions_nearby`、`attractions_types`。
- 住宿：`accommodations_keys`、`accommodations_select`、`accommodations_nearby`。
- 餐饮：`restaurants_keys`、`restaurants_select`、`restaurants_id_is_open`、`restaurants_nearby`、`restaurants_with_recommended_food`、`restaurants_cuisine`。
- 交通与辅助：`intercity_transport_select`、`goto`、`poi_lat_lon_search`、`next_page`。
- 提交：`finalize_plan`，实现位于 `lab/plan_tool.py`。模型选择实体、班次、时段和交通方式；工具从公开沙盒生成真实价格、数量费用、路线及衔接时间，返回修改记录和冲突信息。成功结果直接保存，避免模型再次复制事实字段。

工具查询 benchmark 沙盒，不执行真实订票或付款；隐藏任务查询和通用环境命令不对 Agent 开放。

### 校验、评分与运行记录

- `lab/validation.py`：公开 schema、费用、时间、路线及部分工具证据一致性检查，不读取隐藏标注。
- 提交工具绑定原始公开请求，检查能明确识别的天数与预算；尚非完整中文约束解析器。
- `lab/evaluate.py`：独立调用官方逐任务评分函数，检查 schema、常识约束、硬约束及联合通过情况；未接入偏好指标。缺失输出保留在分母，执行完成不等于评分通过。
- `scripts/apply_upstream_fixes.py`：统一官方交通评分器的一处错误列名，bootstrap 自动应用；已有环境可单独运行该脚本。评分记录补丁状态、源码哈希与异常数。
- `runs/`：保存计划、逐步模型/工具日志、输入输出 tokens、耗时、调用次数和评分。`grounding_queries` 单独统计提交工具内部的逻辑事实读取（含缓存复用），不等于额外模型调用。

## 2. 安装与运行

### 2.1 安装环境并恢复数据

准备 Git、uv 和 Python 3.12。以下为 Windows PowerShell 命令；仓库访问权限需提前开通。

```powershell
git clone https://github.com/IgnacioooZ/multi-agent-travel-planner.git
cd multi-agent-travel-planner
uv python install 3.12
uv sync --frozen
.venv\Scripts\python.exe scripts/bootstrap.py
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

已有项目直接在项目根目录执行安装步骤，不要重复克隆。首次恢复需要访问 GitHub 和 Hugging Face；已恢复的数据可用于离线工具查询和评分。macOS/Linux 将 Python 路径替换为 `.venv/bin/python`，并使用对应 shell 的复制命令；当前本地验收环境为 Windows。

在本地 `.env` 填写模型配置，密钥不提交到仓库：

```dotenv
DEEPSEEK_API_KEY=填写自己的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

模型 ID 必须由账号支持。若更换模型，需重新记录配置并运行两组对照，不能混用不同模型的结果。

### 2.2 检查环境与工具

```powershell
.venv\Scripts\python.exe -m lab.cli doctor
.venv\Scripts\python.exe -m lab.cli smoke
.venv\Scripts\python.exe -m lab.cli mcp-check
.venv\Scripts\python.exe -m pytest -q
```

以上命令不发起付费模型请求。`smoke` 检查数据、direct/MCP 查询和评分器；`mcp-check` 检查协议握手、工具发现、调用与错误处理。

查看任务、工具定义或手动执行查询：

```powershell
.venv\Scripts\python.exe -m lab.cli inspect --split easy --limit 1
.venv\Scripts\python.exe -m lab.cli tools
.venv\Scripts\python.exe -m lab.cli tools --name attractions_select
.venv\Scripts\python.exe -m lab.cli call attractions_select --args-file examples/mcp/attractions.json
```

### 2.3 运行同一任务的单/多智能体版本

下面的 UID 属于固定开发集。两条命令使用同一任务、模型配置、MCP 工具及总调用预算，会产生 DeepSeek API 费用。

```powershell
$taskUid = "e20241028160248698752"
.venv\Scripts\python.exe -m lab.cli run --mode single --transport mcp --uid $taskUid
.venv\Scripts\python.exe -m lab.cli run --mode multi --transport mcp --uid $taskUid
```

批量任务使用 `--subset dev --limit 10`；留出集使用 `--subset holdout --limit 20`。`medium`、`human` 不使用本地 easy 划分，需指定 `--split medium --subset all` 或 `--split human --subset all`，并设置 `--limit`。

`tools`、`call` 和 `run` 默认使用 MCP；需要直接调用对照时指定 `--transport direct`。

### 2.4 评分与查看结果

复现本次 4 easy + 3 medium + 3 human 的多智能体试运行，可执行以下命令（会产生新的 API 费用）。默认不限制累计 token，三个划分分别运行并自动离线评分：

```powershell
.venv\Scripts\python.exe scripts/run_pilot.py --counts 4 3 3
```

冻结的 UID、配置、代码快照和汇总结果保存在对应 `runs/*-pilot10-*/` 中。

每次运行结束会打印结果目录。对 single 和 multi 的目录分别执行：

```powershell
.venv\Scripts\python.exe -m lab.evaluate "runs/替换为实际运行目录"
```

结果目录包含：

```text
runs/日期时间-split-mode-随机后缀/
  run.json                  任务列表、数据版本与运行配置
  metrics_summary.json      整批调用数、tokens 和执行状态
  evaluation_summary.json   评分后生成的汇总
  <uid>/
    task.json               当前任务
    trace.jsonl             模型请求、响应、工具结果与交接
    plan.json               成功产出的计划；运行失败时可能不存在
    metrics.json            本任务状态、耗时和用量
    evaluation.json         评分后生成的逐任务结果
```


## 3. 后续工作

1. **完成失败任务的跑通与优化**：补充餐厅重复规则，改善预算与时间的联合规划；保留逐条失败分析，修改后在相同任务、模型与预算下复测。
2. **单/多智能体对照**：使用相同模型、工具、任务与总预算，比较完整成功率、tokens、调用次数和耗时。single 尚未实测，不能据现有结果断言多智能体更优。
3. **上下文管理**：尝试候选裁剪、证据去重、结构化交接与保留来源的摘要，检查价格、实体和时间约束是否丢失。
4. **评测扩展**：增加任务覆盖与重复运行；分别做消融，冻结方法后再评测留出集，按准确性与成本比较效果。

任务安排见 [TASKS.md](TASKS.md)，交接记录见 [HANDOFF.md](HANDOFF.md)，Git 协作方法见 [协作说明](docs/collaboration.md)。

数据来源：[ChinaTravel Query](https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel)、[ChinaTravel Sandbox](https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel-Sandbox)。上游代码与文档采用 MIT，官方数据采用 CC BY 4.0；研究报告应引用 ChinaTravel 论文。

## 4. 测试结果

最终版本使用 multi + MCP、DeepSeek `deepseek-chat`（服务返回 `deepseek-flash`），在固定的 10 条开发任务上各运行一次。完整通过要求 schema、常识约束与硬约束同时通过，缺失计划计为失败。

- **easy：4/4，100%**。
- **medium：2/3，66.7%**。
- **human：2/3，66.7%**。
- **合计：8/10，80%**；生成正式计划 9/10，90%。

44 项自动化测试通过；本批次评分器异常、token 截断均为 0。输入输出合计 4,143,511 tokens，165 次模型请求、400 次工具调用，另有 611 条内部逻辑事实读取记录。

剩余两条分别为预算/时间联合规划未收敛，以及重复餐厅规则漏检。以上为开发任务的单次结果，不代表完整 benchmark 或留出集性能。发布的逐条结果与配置见 [结果清单](docs/experiments/latest-results.json)。
