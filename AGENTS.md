# AGENTS\.md

## 开工流程

写代码前先做这些事：

1. 用 `pwd` 确认当前目录。

2. 读取 `openspec/progress/progress.md`，了解最新已验证状态和下一步。

3. 读取 `feature_list.json`，选择优先级最高的未完成功能。

4. 用 `git log --oneline -5` 看最近提交。

5. 运行标准启动验证：shell-capable 环境用 `./init.sh`；Windows PowerShell 用 `.\init.cmd`。

6. 在开始新功能前，先跑必需的 smoke test 或端到端验证。

## OpenSpec 变更门禁

新增模块或跨模块功能时，必须先执行以下流程：

1. 执行 `npm run spec:new -- <verb-noun-change-id>` 创建 `openspec/changes/<change-id>/`。
2. 完成 `proposal.md`、`design.md`、`tasks.md` 和受影响 capability 的 delta spec。
3. 执行 `npm run spec:validate`；严格校验通过前不得编写实现代码。
4. 实现期间只勾选已实际完成且已验证的 `tasks.md` 项。
5. 验收完成、`feature_list.json` 和进度记录更新后，才可执行 `npm run spec:archive -- <change-id> --yes`。

`openspec/proposals/` 仅保留历史材料；所有新提案必须放在 `openspec/changes/`。Windows PowerShell 使用 `npm run` 调用本地 OpenSpec，避免全局 `openspec.ps1` 被执行策略拦截。

如果基础验证一开始就失败，先修基础状态，不要在坏的起点上继续叠新功能。

## 工作规则

- 一次只做一个功能。

- 不要因为“代码已经写了”就把功能标记为完成。

- 除非为了消除当前 blocker 的窄范围修复，否则不要扩大到其他功能。

- 实现过程中不要悄悄改弱验证规则。

- 优先依赖仓库里的持久化文件，而不是聊天记录。

## 必需文件

- `feature_list.json`：功能状态的唯一事实来源

- `openspec/progress/progress.md`：会话进度和当前已验证状态

- `init.sh` / `init.ps1` / `init.cmd`：统一的启动与验证入口（分别用于 shell、PowerShell 实现、Windows 直接入口）

- `session-handoff.md`：较长会话可选的交接摘要

## 完成定义

一个功能只有在以下条件都满足时才算完成：

- 目标行为已经实现

- 要求的验证真的跑过

- 证据记录在 `feature_list.json` 或 `openspec/progress/claude-progress.md`

- 仓库仍然能按标准启动路径重新开始工作

## 收尾

结束会话前：

1. 更新 `openspec/progress/claude-progress.md`

2. 更新 `feature_list.json`

3. 记录仍未解决的风险或 blocker

4. 在工作处于安全状态后，用清晰的提交信息提交

5. 保证下一轮会话可以直接运行标准启动入口（shell 用 `./init.sh`；Windows PowerShell 用 `.\init.cmd`）



