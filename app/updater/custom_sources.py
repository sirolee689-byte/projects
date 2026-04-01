from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from app.updater.providers import LatestProvider, LatestRelease
from app.updater.versioning import Version, format_version, parse_version_from_filename

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

@dataclass(frozen=True)
class CustomSource:
    """
    管理员可配置的更新源。
    - update_source_url: 更新源链接（可以是直链，也可以是页面/API；程序会尽量从内容中提取版本号与下载链接）
    """

    software_key: str
    update_source_url: str


_VER_RE = re.compile(r"(\d+(?:\.\d+){1,4})")
_URL_RE = re.compile(r"https?://[^\s\"']+\.(?:exe|msi)(?:\?[^\s\"']+)?", re.IGNORECASE)


def normalize_software_key(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    low = s.casefold()
    if "wechat" in low or "weixin" in low:
        return "微信"
    if low.startswith("qq") or "qqnt" in low or "tencentqq" in low:
        return "QQ"
    if "chrome" in low:
        return "Chrome"
    if "vscode" in low or low == "code" or "visualstudiocode" in low:
        return "VSCode"
    if "wps" in low:
        return "WPS"
    return s


def _pick_best_download_url(candidates: list[str]) -> str | None:
    """
    在候选下载链接中优先选择 64 位安装包。
    规则（从高到低）：包含 x64/64 且不包含 x86/32 -> 不包含 x86/32 -> 取第一个。
    """
    if not candidates:
        return None
    lowered = [(c, c.lower()) for c in candidates]
    prefer64 = [
        c
        for c, lc in lowered
        if (("x64" in lc) or ("64" in lc)) and ("x86" not in lc) and ("32" not in lc)
    ]
    if prefer64:
        return prefer64[0]
    no_x86 = [c for c, lc in lowered if ("x86" not in lc) and ("32" not in lc)]
    if no_x86:
        return no_x86[0]
    return candidates[0]


def _extract_version(text: str) -> Version:
    m = _VER_RE.search(text)
    if not m:
        raise ValueError("未能从返回内容中解析版本号")
    parts = m.group(1).split(".")
    return tuple(int(p) for p in parts)


def load_custom_sources(path: Path) -> list[CustomSource]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("update_sources.json 根节点必须是对象")
    raw_items = data.get("items")
    if raw_items is None:
        return []
    if not isinstance(raw_items, list):
        raise ValueError("update_sources.json.items 必须是数组")
    result: list[CustomSource] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        key = normalize_software_key(str(raw.get("software_key") or "").strip())
        # 新格式：update_source_url
        u = str(raw.get("update_source_url") or "").strip()
        if key and u:
            result.append(CustomSource(key, u))
            continue
        # 旧格式兼容：尽量用 latest_version_url 作为 update_source_url
        lv = str(raw.get("latest_version_url") or "").strip()
        dl = str(raw.get("download_url") or "").strip()
        if key and (lv or dl):
            result.append(CustomSource(key, lv or dl))
    # 去重：同名软件取最后一条
    uniq: dict[str, CustomSource] = {}
    for it in result:
        uniq[it.software_key] = it
    return list(uniq.values())


def save_custom_sources(path: Path, items: list[CustomSource]) -> None:
    uniq: dict[str, CustomSource] = {}
    for it in items:
        key = normalize_software_key(it.software_key)
        url = it.update_source_url.strip()
        if key and url:
            uniq[key] = CustomSource(key, url)
    payload = {
        "schema_version": 2,
        "items": [
            {
                "software_key": it.software_key,
                "update_source_url": it.update_source_url,
            }
            for it in uniq.values()
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class CustomProvider(LatestProvider):
    def __init__(self, src: CustomSource):
        self._src = src

    def get_latest(self) -> LatestRelease:
        url = self._src.update_source_url
        r = requests.get(url, timeout=30, headers=_UA)
        r.raise_for_status()

        # 直接使用响应文本做解析（不要依赖 Content-Type；某些环境/代理会导致头不完整）
        text = r.text or ""

        download_url: str | None = None
        version: Version | None = None

        # 1) JSON：{"version":"x.y.z","download_url":"https://...exe"}
        try:
            js = r.json()
            if isinstance(js, dict):
                if isinstance(js.get("download_url"), str):
                    download_url = js["download_url"].strip()
                if isinstance(js.get("url"), str) and not download_url:
                    download_url = js["url"].strip()
                if isinstance(js.get("version"), str):
                    version = tuple(int(p) for p in js["version"].strip().split(".") if p.strip().isdigit())
        except Exception:  # noqa: BLE001
            pass

        # 2) 文本/HTML：提取第一个 exe/msi URL + 第一个版本号
        if not download_url and text:
            # 微信 Windows 官方页：优先 64 位 WeChatWin_x.y.z.exe
            if "pc.weixin.qq.com" in url.lower():
                m = re.search(
                    r"https?://[^\s\"']+WeChatWin_(\d+(?:\.\d+){1,4})\.exe",
                    text,
                    re.IGNORECASE,
                )
                if m:
                    download_url = m.group(0)
                    version = tuple(int(p) for p in m.group(1).split("."))
            urls = _URL_RE.findall(text)
            best = _pick_best_download_url(urls)
            if best and not download_url:
                download_url = best
        if version is None and text:
            try:
                version = _extract_version(text)
            except Exception:  # noqa: BLE001
                version = None

        # 3) 兜底：update_source_url 本身就是直链
        if not download_url:
            download_url = url

        # 版本兜底：从下载 URL 文件名解析
        if version is None:
            name_guess = Path(urlparse(download_url).path).name
            version = parse_version_from_filename(name_guess) or (0, 0, 0)

        ver_str = format_version(version)
        suffix = Path(urlparse(download_url).path).suffix or ".exe"
        suggested = f"{self._src.software_key}_{ver_str}{suffix}"
        return LatestRelease(self._src.software_key, version, download_url, suggested)


def build_custom_provider_map(items: list[CustomSource]) -> dict[str, LatestProvider]:
    return {it.software_key: CustomProvider(it) for it in items}

