---
name: install-skill-from-github
description: >-
  将 GitHub 上的 Agent Skill（含 SKILL.md 的目录）安装到 Cursor 的技能目录。
  在用户输入 /install-skill、要求从 owner/repo 安装技能、或指定子路径时使用。
  支持公开仓库；私有仓库需本机已配置 git 凭据或 GH_TOKEN。
---

# 从 GitHub 安装 Cursor 技能

## 与 Codex 的区别

- **Cursor** 技能目录：`%USERPROFILE%\.cursor\skills\<技能名>\`（个人）或项目内 `.cursor\skills\<技能名>\`。
- **不要**写入 `~/.cursor/skills-cursor/`（Cursor 内置保留目录）。
- 与 Codex 的 `$CODEX_HOME/skills` **无关**；安装目标必须指向上述 Cursor 路径之一。

## 安装前确认

1. 在浏览器或 `gh repo view owner/repo` 确认仓库存在且可见。
2. 若用户给出 `anthropic/code-understanding-workflow` 但 404，尝试：`anthropics/...`、搜索 GitHub、或请用户提供正确 `owner/repo` 与可选子路径。
3. 确定技能根目录：该目录下必须有 `SKILL.md`（可含 `reference.md`、`scripts/` 等）。

## 默认安装流程（由代理执行）

1. **选定目标目录**  
   - 用户未指定时：优先个人技能 `%USERPROFILE%\.cursor\skills\<basename>\`。  
   - 用户要求写入当前仓库时：`<workspace>\.cursor\skills\<basename>\`。  
   - `basename` 一般为仓库名，或 `--path` 的最后一级目录名。

2. **若目标已存在**  
   - 不要静默覆盖；说明情况并询问是否换名、备份或跳过。

3. **获取文件（任选其一，按环境可用性）**  
   - **git（推荐）**：浅克隆后复制技能子目录，或 sparse checkout 仅拉取所需路径。  
   - **ZIP**：从 `https://github.com/<owner>/<repo>/archive/refs/heads/<ref>.zip` 下载并解压，再复制技能文件夹。  
   - **GitHub CLI**：`gh repo clone owner/repo` 后复制对应子目录。

4. **复制内容**  
   - 将含有 `SKILL.md` 的整个文件夹复制到步骤 1 的目标路径，保持相对结构（含 `scripts/` 等）。

5. **收尾**  
   - 告知用户：新聊天或重载窗口后技能才会稳定生效（按 Cursor 实际行为说明）。  
   - 若仓库为私有且失败：提示配置 `git`/`GH_TOKEN` 或使用 SSH。

## PowerShell 示例（公开仓库、技能在仓库根目录）

将 `OWNER`、`REPO`、`SKILL_FOLDER_NAME` 替换为实际值：

```powershell
$destRoot = Join-Path $env:USERPROFILE ".cursor\skills\SKILL_FOLDER_NAME"
if (Test-Path $destRoot) { throw "目标已存在: $destRoot" }
$tmp = Join-Path $env:TEMP ("gh-skill-" + [guid]::NewGuid().ToString("N"))
git clone --depth 1 "https://github.com/OWNER/REPO.git" $tmp
Copy-Item -Path (Join-Path $tmp "*") -Destination $destRoot -Recurse -Force
Remove-Item $tmp -Recurse -Force
```

技能在子目录 `path/to/skill` 时：克隆后把该子目录内容复制到 `$destRoot`。

## 参数约定

用户可能表述为：

- `/install-skill owner/repo`
- `owner/repo` + 可选子路径 + 可选分支/ref

代理应解析出：`owner`、`repo`、可选 `path`、可选 `ref`（默认 `main`，失败时可试 `master`）。

## 安装后自检

- 目标路径下存在 `SKILL.md`。
- YAML frontmatter 含非空的 `name` 与 `description`。

## 附加说明

若用户本意是 **Codex** 的 `install-skill-from-github.py`，应说明那是 Codex 工作流，并改为按本节将同名技能安装到 **Cursor** 目录。
