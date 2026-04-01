from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import requests

from app.updater.versioning import Version, format_version
from app.updater.versioning import parse_version_from_filename

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}


@dataclass(frozen=True)
class LatestRelease:
    software_key: str
    version: Version
    download_url: str
    suggested_filename: str


class LatestProvider(Protocol):
    def get_latest(self) -> LatestRelease: ...


def _http_get_json(url: str, timeout_seconds: int = 30) -> dict:
    r = requests.get(url, timeout=timeout_seconds, headers=_UA)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise ValueError("返回 JSON 不是对象")
    return data


def _http_get_text(url: str, timeout_seconds: int = 30) -> str:
    r = requests.get(url, timeout=timeout_seconds, headers=_UA)
    r.raise_for_status()
    return r.text


class VSCodeProvider:
    """
    VSCode 官方更新 API。
    文档/行为相对稳定：返回包含 version 与 url 的 JSON。
    """

    def __init__(self, arch: str = "win32-x64", channel: str = "stable"):
        self._arch = arch
        self._channel = channel

    def get_latest(self) -> LatestRelease:
        api = f"https://update.code.visualstudio.com/api/update/{self._arch}/{self._channel}/latest"
        data = _http_get_json(api)
        ver_str = str(data.get("version") or "").strip()
        url = str(data.get("url") or "").strip()
        if not ver_str or not url:
            raise ValueError("VSCode 更新 API 返回缺少 version/url")
        version = tuple(int(p) for p in ver_str.split("."))
        ext = ".exe"
        name = f"VSCode_{format_version(version)}{ext}"
        return LatestRelease("VSCode", version, url, name)


class ChromeProvider:
    """
    Chrome：使用 OmahaProxy 获取稳定版版本号；下载使用官方离线安装包直链。
    """

    def __init__(self, arch: str = "win64", channel: str = "stable"):
        self._arch = arch
        self._channel = channel

    def get_latest(self) -> LatestRelease:
        # OmahaProxy 返回 all.json 数组
        txt = _http_get_text("https://omahaproxy.appspot.com/all.json")
        raw = json.loads(txt)
        if not isinstance(raw, list):
            raise ValueError("OmahaProxy 返回不是数组")
        version_str: str | None = None
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("os") or "").lower() != "win":
                continue
            versions = entry.get("versions")
            if not isinstance(versions, list):
                continue
            for v in versions:
                if not isinstance(v, dict):
                    continue
                if str(v.get("channel") or "").lower() != self._channel:
                    continue
                if str(v.get("current_version") or "").strip():
                    version_str = str(v.get("current_version")).strip()
                    break
            if version_str:
                break
        if not version_str:
            raise ValueError("未能从 OmahaProxy 获取 Chrome 最新版本")
        version = tuple(int(p) for p in version_str.split("."))
        # 官方离线包（企业版）直链：文件名固定但内容为最新版
        url = "https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi"
        name = f"Chrome_{format_version(version)}.msi"
        return LatestRelease("Chrome", version, url, name)


_PCQQ_VERSION_RE = re.compile(r"\n\s*(\d+(?:\.\d+){1,4})\s*\n\s*版本\s*\n", re.IGNORECASE)


def _extract_pcqq_version(html: str) -> Version:
    m = _PCQQ_VERSION_RE.search(html)
    if not m:
        raise ValueError("未能从 pc.qq.com 页面解析版本号")
    parts = m.group(1).strip().split(".")
    return tuple(int(p) for p in parts)


class WeChatProvider:
    """
    微信：兜底更新源（优先建议使用管理员自定义更新源）。从微信 Windows 官方页解析 64 位版本与直链。
    """

    def get_latest(self) -> LatestRelease:
        html = _http_get_text("https://pc.weixin.qq.com/")
        # 页面里有 64 位直链：WeChatWin_x.y.z.exe
        m = re.search(r"https?://[^\s\"']+WeChatWin_(\d+(?:\.\d+){1,4})\.exe", html, re.IGNORECASE)
        if not m:
            raise ValueError("未能从 pc.weixin.qq.com 页面解析 64 位下载链接/版本号")
        ver_str = m.group(1)
        version = tuple(int(p) for p in ver_str.split("."))
        url = m.group(0)
        name = f"微信_{format_version(version)}.exe"
        return LatestRelease("微信", version, url, name)


class QQProvider:
    """
    QQ：版本号从腾讯软件中心页面解析；下载使用腾讯官方直链（文件名固定，内容为最新版）。
    """

    def get_latest(self) -> LatestRelease:
        html = _http_get_text("https://pc.qq.com/detail/14/detail_35094.html")
        version = _extract_pcqq_version(html)
        url = "https://dldir1.qq.com/qqfile/qq/QQNT/Windows/QQSetup.exe"
        name = f"QQ_{format_version(version)}.exe"
        return LatestRelease("QQ", version, url, name)


class WPSProvider:
    """
    WPS：尽量从官网页面中提取下载直链与版本号。
    由于官网页面可能调整，本 provider 以“可用优先”，失败时会给出清晰错误，方便后续扩展。
    """

    _URL_RE = re.compile(r"https?://[^\\s\"']+\\.(?:exe|msi)", re.IGNORECASE)
    _VER_HINT_RE = re.compile(r"\\b(\\d+\\.\\d+(?:\\.\\d+){0,3})\\b")

    def get_latest(self) -> LatestRelease:
        html = _http_get_text("https://www.wps.cn/")
        m = self._URL_RE.search(html)
        if not m:
            raise ValueError("未能从 wps.cn 首页找到安装包直链（exe/msi）")
        url = m.group(0)
        fname = url.split("/")[-1].split("?")[0]

        v = parse_version_from_filename(fname)
        if v is None:
            # 兜底：尝试从页面文本中找一个像版本号的字段
            mh = self._VER_HINT_RE.search(html)
            if not mh:
                raise ValueError("未能从安装包文件名/页面中解析 WPS 版本号")
            v = tuple(int(p) for p in mh.group(1).split("."))

        name = f"WPS_{format_version(v)}{Path(fname).suffix or '.exe'}"
        return LatestRelease("WPS", v, url, name)


def get_provider_map() -> dict[str, LatestProvider]:
    """
    内置映射：后续扩展只需要在这里增加 provider。
    约定 key 为 常用软件 下一级文件夹名（例如 Chrome / VSCode / WPS / 微信 / QQ）。
    """
    return {
        "Chrome": ChromeProvider(),
        "VSCode": VSCodeProvider(),
        "微信": WeChatProvider(),
        "QQ": QQProvider(),
        "WPS": WPSProvider(),
    }

