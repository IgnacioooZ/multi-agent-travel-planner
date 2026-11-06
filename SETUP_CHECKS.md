# 搭建验证记录

日期：2026-11-04（Asia/Shanghai）

- VS Code 已打开 chinatravel-lab，Python 与调试扩展已安装。
- 项目独立虚拟环境：Python 3.12.13；依赖由 uv.lock 锁定。
- 官方任务加载完成：easy 300、medium 150、human 154，共 604 条。
- 中文沙盒下载并安装，包含 30 个 CSV 文件及其他交通/位置资源。
- Python 直接调用与 MCP 均发现 18 个 Agent 可用工具。
- 两种调用方式均成功查询杭州景点与上海到杭州火车信息；景点返回值一致。
- 官方 schema、commonsense、hard-constraint 逐任务评分链路可运行，无效行程被拒绝。
- 6 项测试通过：公开输入与划分、隐藏工具隔离、角色交接与计数、全局预算、工具参数错误、模型 SDK 请求与响应适配。
- 单/多智能体角色测试使用脚本化模型；模型 SDK 测试使用本地 HTTP mock，未访问 DeepSeek。

截至搭建完成，DEEPSEEK_API_KEY 未配置，因此没有真实模型推理、付费 API 调用或模型成功率结果。`deepseek-chat` 按用户要求保留，账号是否支持该模型 ID 尚未联网验证。

本次修复：MCP 子进程在 Windows 下回调期间延迟加载原生数值库出现卡顿，改为启动 stdio 工作线程前加载沙盒，并限制其数值计算线程数；MCP 集成自检已通过。官方源码未修改。

机器可读自检结果：`runs/smoke/report.json`。这份结果仅证明基础设施可用，不代表 Agent 通过了旅行任务。

## MCP 完整接入验证：2026-11-05

- `tools`、`call`、`run` 默认使用 MCP；新增独立 `mcp-check`，无需模型密钥。
- 真实 stdio 子进程完成初始化与工具发现，18 个工具的 schema 与直接调用一致；四种查询结果一致。
- 参数缺失、类型错误、枚举错误、未知工具及隐藏工具调用均被拒绝；错误后会话仍可继续使用。
- MCP 服务端返回结构化结果和 `isError`，客户端统一处理成功与失败结果。
- 三个角色通过真实 MCP 完成工具调用与交接的集成测试通过；该测试的模型为脚本化替身。
- 当前完整测试：11 passed（12.32 秒）。
- 本地已配置 DeepSeek 密钥；真实 `deepseek-chat` 连通测试成功，2 次模型调用、1 次工具调用，输入 1814 tokens、输出 146 tokens。此次会产生 API 费用。
- 连通测试报告：`runs/20261105-220509-593543-mcp-model-probe/report.json`；协议自检：`runs/mcp-check/report.json`。

本次验证不包含完整 benchmark 性能评测；不能据此推断旅行任务成功率。手把手操作见 `docs/02-mcp-lab.md`。
