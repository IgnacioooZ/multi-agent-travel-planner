# 共享前验证记录

日期：2026-11-07（Asia/Shanghai）。本记录针对已有本地环境，不表示已验证所有组员的新机器。

- `python -m pytest -q`：11 passed，18.03 秒。
- `python -m lab.cli smoke`：PASS。
- 官方任务数量：easy 300、medium 150、human 154。
- direct 与 MCP 均发现 18 个工具，真实沙盒查询通过。
- 官方评分器成功拒绝无效行程。
- 本次未运行付费模型实验，以上结果不代表旅行规划成功率。
- Git 忽略规则排除 `.env`、`.venv`、下载数据、上游副本及原始运行日志；仅提交 `.env.example` 与固定的 `data/splits.json`。
- 上游 ChinaTravel 工作区未修改，commit 与 `benchmark.lock.json` 一致。

新同学必须按 README 重新安装依赖、恢复数据并复测。代码上传是否成功，以远端仓库实际文件和提交为准。
