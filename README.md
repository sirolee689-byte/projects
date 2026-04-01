# 内网软件助手

Windows 桌面小工具：从内网共享目录浏览安装包、下载到本机并以向导方式安装。基于 **Python 3** + **PySide6**。

## 功能概要

| 能力 | 说明 |
|------|------|
| 自动目录树 | 读取 `share_root` 下多级文件夹，`.exe` / `.msi` 自动出现在树中，**无需**维护软件列表 JSON |
| 下载 | 支持 **UNC** 与 **HTTP(S)**；下载前若本地已有同名文件会询问是否覆盖 |
| 安装 | 仅当本地下载目录中**已有对应文件**时「安装」可点；确认后以系统默认方式运行安装包（图形向导） |
| 同步 | 目录变更监听 + UNC 轮询 + 手动刷新 |

详细变更见 **[CHANGELOG.md](./CHANGELOG.md)**。

## 环境要求

- Windows（本机路径、`explorer`、`os.startfile` 等按 Windows 设计）
- Python 3.10+（建议）

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

或使用模块入口：

```bash
python -m app.main
```

## 配置（`config.json`）

| 字段 | 含义 |
|------|------|
| `share_root` | 共享根路径（如 `\\server\share\apps`），目录结构即分类与层级 |
| `download_dir` | 本机保存安装包的目录 |

共享目录中：**仅包含有安装包的文件夹会出现在树上**；根目录下也可直接放置 `.exe` / `.msi`。

## 项目结构（节选）

```text
main.py
config.json
requirements.txt
CHANGELOG.md
app/
  catalog.py      # 扫描共享目录、生成目录树数据
  config.py       # SoftwareItem 等模型
  downloader.py   # 下载/复制与目标路径
  installer.py    # 启动安装包、打开下载文件夹
  settings.py     # 读取 config.json
  ui/main_window.py
```

## 许可证

对外发布到 GitHub 时，请自行添加 `LICENSE` 并在本段写明授权方式。
