# 内网软件助手（桌面端）

这是一个用于公司内网环境的软件下载安装助手（Windows），基于 **PySide6** 开发。

## 目录结构

```text
UB_AI/
  main.py
  config.json
  app/
    __init__.py
    main.py
    config.py
    settings.py
    downloader.py
    installer.py
    ui/
      __init__.py
      main_window.py
  software_list.json
  requirements.txt
  README.md
  .gitignore
```

## 安装依赖

在该目录下执行：

```bash
pip install -r requirements.txt
```

## 运行

```bash
python main.py
```

也可以：

```bash
python -m app.main
```

## 配置说明（software_list.json）

- **name**：软件名
- **download_url**：下载源（支持内网 UNC 路径如 `\\192.168.1.33\tools\apps\xxx.exe`，也兼容 HTTP/HTTPS）
- **version**：版本号（仅展示用）
- **silent_args**：静默安装参数（不同安装包不同）
- **tutorial**：安装教程说明（支持换行）

## 基础配置（config.json）

- **download_dir**：下载到本地的目录（例如 `C:\Temp\InternalApp`）
- **share_root**：共享目录根路径（例如 `\\192.168.1.33\tools\apps`）

