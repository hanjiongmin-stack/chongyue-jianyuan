"""页面公共片段注入。

页面中的 <!--cy:名称--> 会被替换为 static/partials/名称.html；页面和片段里的 %%V%%
替换为 static/assets 下共享样式与脚本的内容哈希，用于绕过 /assets 的长缓存。
"""

import hashlib
import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
_PARTIALS_DIR = STATIC_DIR / "partials"
_PARTIAL_RE = re.compile(r"<!--cy:([a-z0-9-]+)-->")
_partial_cache: dict = {}
_asset_version_cache: dict = {}


def asset_version() -> str:
    # 顶层共享样式/脚本（cyjy.*、chem.*、admin-content.* 等）任一变化都会刷新版本号
    try:
        files = sorted(
            f for f in (STATIC_DIR / "assets").iterdir()
            if f.is_file() and f.suffix in (".css", ".js")
        )
        key = tuple((f.name, f.stat().st_mtime_ns) for f in files)
    except OSError:
        return "0"
    if _asset_version_cache.get("key") != key:
        digest = hashlib.md5(b"".join(f.read_bytes() for f in files)).hexdigest()[:10]
        _asset_version_cache.update(key=key, value=digest)
    return _asset_version_cache["value"]


def _partial(name: str) -> str:
    path = _PARTIALS_DIR / f"{name}.html"
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return ""
    cached = _partial_cache.get(name)
    if not cached or cached[0] != mtime:
        cached = (mtime, path.read_text(encoding="utf-8"))
        _partial_cache[name] = cached
    return cached[1]


def apply_partials(body: str) -> str:
    if "<!--cy:" not in body and "%%V%%" not in body:
        return body
    body = _PARTIAL_RE.sub(lambda m: _partial(m.group(1)), body)
    return body.replace("%%V%%", asset_version())
