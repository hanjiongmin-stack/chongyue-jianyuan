"""站点内容存储：管理后台修改的页面、学习资源数据和上传文件保存在哪里。

线上的 Render 免费实例磁盘是临时的，直接写本地文件会在重启后丢失，所以提供两种模式：

- GitHub 模式（设置了 CYJY_GITHUB_TOKEN）：
  文本文件（页面 HTML、seed_resources.json）直接提交到仓库，提交信息带 [skip render]，
  不会触发重新部署，同时写入本地让修改立即生效；上传的文件保存为仓库 Release「site-files」
  的附件，不会让仓库本身越来越大。实例重启后，启动阶段会把仓库中比本地新的内容文件同步下来。
- 本地模式：直接读写项目目录，适合本地开发，或挂载了持久化磁盘的部署。
  在 Render 上没有配置令牌时为只读，避免修改在重启后悄悄丢失。
"""

import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import os
import secrets
import time
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("content_store")

GITHUB_TOKEN = os.environ.get("CYJY_GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("CYJY_GITHUB_REPO", "hanjiongmin-stack/chongyue-jianyuan").strip()
GITHUB_BRANCH = os.environ.get("CYJY_GITHUB_BRANCH", "main").strip()
GITHUB_API = os.environ.get("CYJY_GITHUB_API", "https://api.github.com").strip().rstrip("/")
IS_RENDER = bool(os.environ.get("RENDER"))
LOCAL_WRITE = os.environ.get("CYJY_CONTENT_LOCAL_WRITE", "").strip().lower() in ("1", "true", "yes")

RELEASE_TAG = "site-files"
LOCAL_MEDIA_DIR = BASE_DIR / "static" / "uploads" / "files"
LOCAL_MEDIA_INDEX = LOCAL_MEDIA_DIR / "_index.json"
MAX_TEXT_BYTES = 2 * 1024 * 1024


class ContentError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def git_blob_sha(data: bytes) -> str:
    """与 Git 相同的 blob 哈希，用于判断本地文件与仓库是否一致。"""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def is_sync_path(path: str) -> bool:
    """管理后台可以修改、启动时需要从仓库同步的内容文件。"""
    if path in ("seed_resources.json", "seed_categories_tags.json",
                "static/partials/nav.html", "static/partials/footer.html"):
        return True
    if path.endswith(".html") and path.count("/") == 1 and path.startswith("static/"):
        return path != "static/admin.html"
    return path.endswith(".html") and path.startswith("static/chemistry/") and path.count("/") == 2


def _local_path(rel: str) -> Path:
    p = (BASE_DIR / rel).resolve()
    if BASE_DIR not in p.parents:
        raise ContentError("非法路径", 400)
    return p


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _sync_enabled() -> bool:
    return IS_RENDER or os.environ.get("CYJY_CONTENT_SYNC", "").strip() == "1"


def _media_ext(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return ext if ext and len(ext) <= 10 and ext[1:].isalnum() else ""


class ContentStore:
    def __init__(self):
        self._http = None
        self._release = None
        self._assets = None          # key -> asset 信息（GitHub 模式）
        self._assets_at = 0.0
        self._lock = asyncio.Lock()

    # ── 状态 ────────────────────────────────────────────
    @property
    def mode(self) -> str:
        return "github" if GITHUB_TOKEN else "local"

    @property
    def writable(self) -> bool:
        return bool(GITHUB_TOKEN) or not IS_RENDER or LOCAL_WRITE

    def status(self) -> dict:
        info = {"mode": self.mode, "writable": self.writable}
        if self.mode == "github":
            info.update(repo=GITHUB_REPO, branch=GITHUB_BRANCH)
        elif not self.writable:
            info["reason"] = "线上环境没有配置 CYJY_GITHUB_TOKEN：修改会在实例重启后丢失，因此暂时只读。"
        return info

    def require_writable(self) -> None:
        if not self.writable:
            raise ContentError(self.status()["reason"], 409)

    # ── GitHub API ──────────────────────────────────────
    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(20.0, read=120.0), follow_redirects=True)
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self, accept: str = "application/vnd.github+json") -> dict:
        return {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "chongyue-jianyuan-admin",
        }

    async def _gh(self, method: str, url: str, **kw) -> httpx.Response:
        if not url.startswith("http"):
            url = f"{GITHUB_API}/repos/{GITHUB_REPO}{url}"
        headers = self._headers(kw.pop("accept", "application/vnd.github+json"))
        headers.update(kw.pop("headers", {}))
        client = await self._client()
        try:
            return await client.request(method, url, headers=headers, **kw)
        except httpx.HTTPError as e:
            logger.warning(f"GitHub 请求失败: {method} {url.split('?')[0]} ({e.__class__.__name__})")
            raise ContentError("无法连接 GitHub，请稍后重试")

    @staticmethod
    def _gh_message(r: httpx.Response) -> str:
        try:
            return str(r.json().get("message") or "").strip()
        except Exception:
            return ""

    @classmethod
    def _gh_error(cls, r: httpx.Response, action: str) -> ContentError:
        msg = cls._gh_message(r)
        logger.warning(f"GitHub {action} 失败: HTTP {r.status_code} {msg[:120]}")
        if r.status_code in (401, 403):
            return ContentError(f"GitHub 拒绝了{action}请求（{r.status_code}）：请检查 CYJY_GITHUB_TOKEN 是否有效、是否授予了本仓库的 Contents 读写权限")
        if r.status_code == 404:
            return ContentError(f"{action}失败：仓库、分支或文件不存在（请检查 CYJY_GITHUB_REPO / CYJY_GITHUB_BRANCH）", 404)
        detail = msg.splitlines()[0][:120] if msg else ""
        return ContentError(f"{action}失败（GitHub 返回 {r.status_code}{'：' + detail if detail else ''}）")

    # ── 文本文件 ────────────────────────────────────────
    async def read_text(self, rel: str) -> dict:
        """读取文件。GitHub 模式以仓库最新版本为准，并顺带更新本地副本。"""
        local = _local_path(rel)
        if self.mode == "local":
            if not local.exists():
                raise ContentError("文件不存在", 404)
            data = local.read_bytes()
            return {"content": data.decode("utf-8"), "sha": git_blob_sha(data)}
        r = await self._gh("GET", f"/contents/{rel}", params={"ref": GITHUB_BRANCH})
        if r.status_code != 200:
            raise self._gh_error(r, "读取文件")
        meta = r.json()
        if meta.get("encoding") == "base64" and meta.get("content"):
            data = base64.b64decode(meta["content"])
        else:  # 大于 1 MB 的文件需要单独取原始内容
            raw = await self._gh("GET", f"/contents/{rel}", params={"ref": GITHUB_BRANCH},
                                 accept="application/vnd.github.raw+json")
            if raw.status_code != 200:
                raise self._gh_error(raw, "读取文件")
            data = raw.content
        if _sync_enabled() and (not local.exists() or git_blob_sha(local.read_bytes()) != meta["sha"]):
            _atomic_write(local, data)  # 线上实例顺带更新本地副本；本地开发时不覆盖工作区里未提交的修改
        return {"content": data.decode("utf-8"), "sha": meta["sha"]}

    async def write_text(self, rel: str, text: str, message: str, sha: str = None) -> dict:
        """保存文件。sha 是编辑开始时的版本，用来发现并阻止覆盖别人的修改；为空表示总是覆盖。"""
        self.require_writable()
        data = text.encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            raise ContentError("文件超过 2 MB，无法保存", 413)
        local = _local_path(rel)
        if self.mode == "local":
            if sha and local.exists() and git_blob_sha(local.read_bytes()) != sha:
                raise ContentError("文件在你编辑期间已被修改，请重新加载后再保存", 409)
            _atomic_write(local, data)
            return {"sha": git_blob_sha(data)}

        async with self._lock:
            for attempt in range(2):
                base_sha = sha
                if not base_sha:
                    cur = await self._gh("GET", f"/contents/{rel}", params={"ref": GITHUB_BRANCH})
                    base_sha = cur.json().get("sha") if cur.status_code == 200 else None
                body = {
                    "message": f"{message} [skip render]",
                    "content": base64.b64encode(data).decode("ascii"),
                    "branch": GITHUB_BRANCH,
                }
                if base_sha:
                    body["sha"] = base_sha
                r = await self._gh("PUT", f"/contents/{rel}", json=body)
                if r.status_code in (200, 201):
                    res = r.json()
                    _atomic_write(local, data)
                    commit = res.get("commit") or {}
                    return {"sha": (res.get("content") or {}).get("sha"), "commit": commit.get("sha"),
                            "commit_url": commit.get("html_url")}
                # 版本号过期是 409「does not match」或 422「sha」；分支保护等其他原因原样报告
                msg = self._gh_message(r) if r.status_code in (409, 422) else ""
                stale = "does not match" in msg or "sha" in msg.lower()
                if stale and not sha and attempt == 0:
                    continue  # 服务端生成的文件：取最新版本号后重试一次
                if stale:
                    raise ContentError("文件在你编辑期间已被修改（可能来自另一次保存或代码提交），请重新加载后再保存", 409)
                raise self._gh_error(r, "保存文件")
        raise ContentError("保存文件失败，请稍后重试")

    async def history(self, rel: str, limit: int = 20) -> list:
        if self.mode == "local":
            return []
        r = await self._gh("GET", "/commits", params={"path": rel, "sha": GITHUB_BRANCH, "per_page": limit})
        if r.status_code != 200:
            raise self._gh_error(r, "读取历史版本")
        out = []
        for c in r.json():
            info = c.get("commit") or {}
            author = info.get("author") or {}
            out.append({
                "sha": c.get("sha"),
                "message": (info.get("message") or "").split("\n")[0].replace(" [skip render]", ""),
                "date": author.get("date"),
                "author": author.get("name") or "",
                "url": c.get("html_url"),
            })
        return out

    async def read_text_at(self, rel: str, ref: str) -> str:
        if self.mode == "local":
            raise ContentError("本地模式没有版本历史，请使用 git 查看", 400)
        r = await self._gh("GET", f"/contents/{rel}", params={"ref": ref}, accept="application/vnd.github.raw+json")
        if r.status_code != 200:
            raise self._gh_error(r, "读取历史版本")
        return r.content.decode("utf-8")

    # ── 启动同步 ────────────────────────────────────────
    async def sync_from_remote(self) -> list:
        """把仓库中与本地不同的内容文件写入本地（只在 Render 上、GitHub 模式下执行）。"""
        if self.mode != "github" or not _sync_enabled():
            return []
        r = await self._gh("GET", f"/git/trees/{GITHUB_BRANCH}", params={"recursive": "1"})
        if r.status_code != 200:
            raise self._gh_error(r, "同步内容")
        updated = []
        for entry in r.json().get("tree", []):
            path = entry.get("path", "")
            if entry.get("type") != "blob" or not is_sync_path(path):
                continue
            local = _local_path(path)
            if local.exists() and git_blob_sha(local.read_bytes()) == entry.get("sha"):
                continue
            blob = await self._gh("GET", f"/git/blobs/{entry['sha']}")
            if blob.status_code != 200:
                raise self._gh_error(blob, "同步内容")
            _atomic_write(local, base64.b64decode(blob.json()["content"]))
            updated.append(path)
        return updated

    # ── 文件库 ──────────────────────────────────────────
    async def _ensure_release(self) -> dict:
        if self._release:
            return self._release
        r = await self._gh("GET", f"/releases/tags/{RELEASE_TAG}")
        if r.status_code == 404:
            r = await self._gh("POST", "/releases", json={
                "tag_name": RELEASE_TAG,
                "target_commitish": GITHUB_BRANCH,
                "name": "站点文件",
                "body": "网站管理后台上传的文件（学习资源附件、页面中引用的文档与图片）。网站直接引用这些附件，请不要删除。",
                "prerelease": True,
            })
        if r.status_code not in (200, 201):
            raise self._gh_error(r, "准备文件库")
        self._release = r.json()
        return self._release

    @staticmethod
    def _asset_item(a: dict) -> dict:
        return {
            "key": a["name"],
            "name": a.get("label") or a["name"],
            "size": a.get("size") or 0,
            "content_type": a.get("content_type") or "application/octet-stream",
            "created_at": a.get("created_at"),
            "id": a["id"],
        }

    async def _load_assets(self, force: bool = False) -> dict:
        if self._assets is not None and not force and time.time() - self._assets_at < 600:
            return self._assets
        rel = await self._ensure_release()
        assets, page = {}, 1
        while True:
            r = await self._gh("GET", f"/releases/{rel['id']}/assets", params={"per_page": 100, "page": page})
            if r.status_code != 200:
                raise self._gh_error(r, "读取文件库")
            batch = r.json()
            for a in batch:
                item = self._asset_item(a)
                assets[item["key"]] = item
            if len(batch) < 100:
                break
            page += 1
        self._assets, self._assets_at = assets, time.time()
        return assets

    @staticmethod
    def _read_local_index() -> dict:
        try:
            return json.loads(LOCAL_MEDIA_INDEX.read_text(encoding="utf-8"))
        except Exception:
            return {}

    async def media_list(self) -> list:
        if self.mode == "local":
            items = []
            for key, meta in self._read_local_index().items():
                if (LOCAL_MEDIA_DIR / key).is_file():
                    items.append({"key": key, **meta})
        else:
            items = list((await self._load_assets(force=True)).values())
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return [{k: v for k, v in it.items() if k != "id"} for it in items]

    async def media_get(self, key: str) -> dict:
        if self.mode == "local":
            meta = self._read_local_index().get(key)
            if meta and (LOCAL_MEDIA_DIR / key).is_file():
                return {"key": key, **meta}
            return None
        assets = await self._load_assets()
        if key not in assets:
            assets = await self._load_assets(force=True)
        return assets.get(key)

    async def media_upload(self, filename: str, data: bytes, content_type: str = "") -> dict:
        self.require_writable()
        ext = _media_ext(filename)
        key = f"{int(time.time()):x}-{secrets.token_hex(4)}{ext}"
        ctype = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if self.mode == "local":
            async with self._lock:
                _atomic_write(LOCAL_MEDIA_DIR / key, data)
                index = self._read_local_index()
                index[key] = {"name": filename, "size": len(data), "content_type": ctype,
                              "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                _atomic_write(LOCAL_MEDIA_INDEX, json.dumps(index, ensure_ascii=False, indent=1).encode("utf-8"))
            return {"key": key, **index[key]}
        rel = await self._ensure_release()
        upload_url = rel["upload_url"].split("{", 1)[0]
        r = await self._gh("POST", upload_url, params={"name": key, "label": filename},
                           content=data, headers={"Content-Type": ctype})
        if r.status_code != 201:
            raise self._gh_error(r, "上传文件")
        item = self._asset_item(r.json())
        if self._assets is not None:
            self._assets[key] = item
        return {k: v for k, v in item.items() if k != "id"}

    async def media_delete(self, key: str) -> None:
        self.require_writable()
        if self.mode == "local":
            async with self._lock:
                index = self._read_local_index()
                if key not in index:
                    raise ContentError("文件不存在", 404)
                index.pop(key)
                (LOCAL_MEDIA_DIR / key).unlink(missing_ok=True)
                _atomic_write(LOCAL_MEDIA_INDEX, json.dumps(index, ensure_ascii=False, indent=1).encode("utf-8"))
            return
        item = await self.media_get(key)
        if not item:
            raise ContentError("文件不存在", 404)
        r = await self._gh("DELETE", f"/releases/assets/{item['id']}")
        if r.status_code not in (204, 404):
            raise self._gh_error(r, "删除文件")
        if self._assets is not None:
            self._assets.pop(key, None)

    async def media_open(self, key: str, range_header: str = None):
        """返回 (item, 本地路径或上游响应)。上游响应需要调用方负责关闭。"""
        item = await self.media_get(key)
        if not item:
            return None, None
        if self.mode == "local":
            return item, LOCAL_MEDIA_DIR / key
        extra = {"Range": range_header} if range_header else {}
        client = await self._client()
        try:
            # GitHub 会重定向到临时下载地址：手动跟随，并且不把令牌带到重定向目标
            req = client.build_request("GET", f"{GITHUB_API}/repos/{GITHUB_REPO}/releases/assets/{item['id']}",
                                       headers={**self._headers("application/octet-stream"), **extra})
            resp = await client.send(req, stream=True, follow_redirects=False)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                location = resp.headers["location"]
                await resp.aclose()
                req = client.build_request("GET", location, headers={"User-Agent": "chongyue-jianyuan-admin", **extra})
                resp = await client.send(req, stream=True, follow_redirects=False)
        except httpx.HTTPError as e:
            logger.warning(f"读取文件库文件失败: {key} ({e.__class__.__name__})")
            raise ContentError("文件暂时无法读取，请稍后重试")
        return item, resp


store = ContentStore()
