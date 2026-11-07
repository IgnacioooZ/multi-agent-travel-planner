# 小组协作说明

本项目使用同一仓库的 `main` 分支按顺序接力，同一时间只有一位同学提交修改。安装和运行命令见 [README](../README.md)。

## 首次加入

仓库负责人在 GitHub 的 Settings → Collaborators → Add people 邀请组员。组员接受邀请后克隆仓库，按 README 恢复环境。仅有仓库链接不等于获得私有仓库权限。

在本仓库设置提交署名：

```powershell
git config user.name "你的名字"
git config user.email "你的 GitHub 提交邮箱"
```

署名不等于登录。首次推送需要认证时，使用 Git/VS Code 的正式登录流程。各自配置本地 `.env`，不上传密钥、虚拟环境、下载数据或原始运行日志。

## 接手前

先在组内确认轮到自己，再阅读 [TASKS.md](../TASKS.md) 与 [HANDOFF.md](../HANDOFF.md)。

```powershell
git status
git branch --show-current
git pull --ff-only origin main
```

应位于 `main`，并先处理已有的未提交修改。若历史分叉导致更新失败，保留当前工作并与上一位确认，不使用强制推送或强制重置。

## 完成后

运行 `pytest`；涉及工具、MCP 或评分链路时额外运行 `smoke`。更新任务状态和交接记录，写明实际测试结果、已知问题、下一步以及依赖是否变化。

```powershell
git status
git diff
git add .
git diff --cached --stat
git diff --cached
git commit -m "简要说明本次修改"
git push origin main
git status
git log -1 --oneline
```

提交前核对暂存内容；只有推送成功，下一位才能获取修改。如果推送被拒绝，先确认远端变化，不使用 `push --force`。核对 GitHub 上的最新提交后，由负责人在组内发送交接消息。

任务讨论可使用仓库 Issues 和现有任务模板；以 TASKS.md 为执行顺序，负责人和时间由小组填写。
