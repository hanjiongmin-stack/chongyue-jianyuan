"""Read-only GitHub vocabulary feed, shared by all website visitors."""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from auth import get_current_user
from content_store import store as content_store, ContentError
from docx_export import build_vocab_docx
from models import User
from security import RateLimiter

router = APIRouter(tags=["vocabulary"])
BASE_DIR = Path(__file__).resolve().parent.parent
REPO = "hanjiongmin-stack/chongyue-jianyuan"
BRANCH = os.environ.get("CYJY_VOCAB_BRANCH", "main")
DATA_PATH = os.environ.get("CYJY_VOCAB_PATH", "content/ielts-words.json")
VOCAB_REL_PATH = "content/ielts-words.json"
# 登录用户添加单词：同一账号每分钟最多 10 次
vocab_write_limiter = RateLimiter(max_requests=10, window_seconds=60)
SOURCE_URL = f"https://github.com/{REPO}/blob/{quote(BRANCH, safe='')}/{quote(DATA_PATH, safe='/')}"
RAW_URL = f"https://raw.githubusercontent.com/{REPO}/{quote(BRANCH, safe='')}/{quote(DATA_PATH, safe='/')}"
MAX_BYTES = 2 * 1024 * 1024


def normalize_words(payload):
    """Accept the original notebook's exported array or a {words: [...]} feed."""
    rows = payload.get("words") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("单词数据必须为数组，且不超过 10000 条")
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("word"), str) or not row["word"].strip():
            raise ValueError("单词记录缺少有效的 word 字段")
        item = {}
        for key in ("word", "phonetic", "zh"):
            value = row.get(key, "")
            if not isinstance(value, str) or len(value) > 10000:
                raise ValueError(f"无效的 {key} 字段")
            item[key] = value.strip()
        groups = row.get("zhGroups", [])
        if not isinstance(groups, list) or any(
            not isinstance(g, dict) or not isinstance(g.get("text", ""), str)
            or not isinstance(g.get("pos", ""), str) for g in groups
        ):
            raise ValueError("无效的 zhGroups 字段")
        item["zhGroups"] = [{"pos": g.get("pos", ""), "text": g.get("text", "")} for g in groups]
        created = row.get("createdAt")
        item["createdAt"] = created if type(created) in (int, float) and 0 < created < 8640000000000000 else None
        result.append(item)
    return result


def sort_words(rows):
    """清单按单词字母 A–Z 保存（大小写不敏感），这样仓库里的文件和导出结果都是有序的。"""
    return sorted(rows, key=lambda r: (str(r.get("word", "")).casefold(), str(r.get("word", ""))))


class VocabularyFeed:
    def __init__(self):
        self.words = None
        self.etag = None
        self.checked_at = None
        self.next_check = 0
        self.error = None
        self.lock = asyncio.Lock()

    async def snapshot(self):
        async with self.lock:
            if time.monotonic() >= self.next_check:
                try:
                    headers = {"User-Agent": "ChongYue-JianYuan-Vocabulary", "Cache-Control": "no-cache"}
                    if self.etag:
                        headers["If-None-Match"] = self.etag
                    async with httpx.AsyncClient(timeout=12) as client:
                        async with client.stream("GET", RAW_URL, headers=headers) as response:
                            if response.status_code == 404:
                                raise ValueError("尚未找到仓库中的单词数据文件，请联系站点维护者")
                            if response.status_code == 304 and self.words is not None:
                                pass
                            else:
                                response.raise_for_status()
                                chunks = bytearray()
                                async for chunk in response.aiter_bytes():
                                    chunks.extend(chunk)
                                    if len(chunks) > MAX_BYTES:
                                        raise ValueError("单词文件超过 2 MB 限制")
                                words = normalize_words(json.loads(chunks))
                                self.words = words
                                self.etag = response.headers.get("etag")
                    self.checked_at = datetime.now(timezone.utc).isoformat()
                    self.error = None
                except (httpx.HTTPError, ValueError, UnicodeError):
                    # Keep the last valid snapshot; invalid data must never erase it.
                    self.error = "暂时无法同步仓库，请稍后重试或联系站点维护者检查数据文件"
                finally:
                    # Cache failures too: visitor polling cannot exhaust upstream requests.
                    self.next_check = time.monotonic() + 60
        return {
            "words": self.words if self.words is not None else [],
            "available": self.words is not None,
            "stale": self.error is not None,
            "message": self.error,
            "checkedAt": self.checked_at,
            "sourceUrl": SOURCE_URL,
        }

    async def apply_words(self, words):
        """写入成功后直接采用最新清单，避免 60 秒缓存与 raw CDN 延迟。"""
        async with self.lock:
            self.words = words
            self.checked_at = datetime.now(timezone.utc).isoformat()
            self.error = None
            self.next_check = time.monotonic() + 60


feed = VocabularyFeed()


@router.get("/ielts", response_class=HTMLResponse)
async def vocabulary_page():
    return HTMLResponse((BASE_DIR / "static" / "ielts.html").read_text(encoding="utf-8"))


@router.get("/api/v1/vocabulary")
async def vocabulary_data():
    data = await feed.snapshot()
    return JSONResponse(data, status_code=200 if data["available"] else 503,
                        headers={"Cache-Control": "no-store"})


def _search_rows(rows, query, sort):
    """按与页面一致的规则筛选排序，导出结果和屏幕上看到的顺序保持一致。"""
    key = (query or "").strip().casefold()
    if key:
        rows = [word for word in rows if key in (
            str(word.get("word", "")) + " " + str(word.get("zh", "")) + " "
            + " ".join(str(g.get("text", "")) for g in word.get("zhGroups", []))
        ).casefold()]
    if sort in ("az", "za"):
        items = sort_words(rows)
        return list(reversed(items)) if sort == "za" else items
    # 最新 / 最早记录：按记录时间排，没有时间的排在最后
    return sorted(rows, key=lambda w: w.get("createdAt") or 0, reverse=(sort != "oldest"))


@router.get("/api/v1/vocabulary/export")
async def export_vocabulary(q: str = Query(default=""), sort: str = Query(default="az"),
                            phonetic: bool = Query(default=True)):
    """导出当前筛选/排序结果为 Word：一列英文、一列中文。"""
    data = await feed.snapshot()
    if not data["available"]:
        raise HTTPException(status_code=503, detail="单词数据暂不可用，请稍后重试")
    rows = _search_rows(data["words"], q[:100], sort if sort in ("az", "za", "oldest", "newest") else "az")
    content = build_vocab_docx(rows, phonetic=phonetic)
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
    filename = f"ielts-words-{stamp}.docx"
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename={filename}; "
                                                    f"filename*=UTF-8''{quote(filename)}",
                             "Cache-Control": "no-store"})


class WordCreate(BaseModel):
    word: str = Field(..., min_length=1, max_length=100)
    phonetic: str = Field(default="", max_length=200)
    zh: str = Field(default="", max_length=1000)


@router.post("/api/v1/vocabulary", status_code=201)
async def add_word(payload: WordCreate, request: Request,
                   current_user: User = Depends(get_current_user)):
    """登录用户添加单词：校验后写回仓库 JSON，并立即刷新内存快照。"""
    vocab_write_limiter.limit(request, key=f"user:{current_user.id}")
    word = payload.word.strip()
    if not word:
        raise HTTPException(status_code=422, detail="单词不能为空")
    phonetic = payload.phonetic.strip()
    zh = payload.zh.strip()
    try:
        snap = await content_store.read_text(VOCAB_REL_PATH)
    except ContentError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    try:
        data = json.loads(snap["content"])
    except ValueError:
        raise HTTPException(status_code=500, detail="单词清单格式异常，请联系站点维护者")
    rows = data.get("words") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise HTTPException(status_code=500, detail="单词清单格式异常，请联系站点维护者")
    key = word.casefold()
    if any(isinstance(r, dict) and r.get("word", "").strip().casefold() == key for r in rows):
        raise HTTPException(status_code=409, detail=f"单词「{word}」已经在记录中了")
    new_word = {
        "word": word,
        "phonetic": phonetic,
        "zh": zh,
        "createdAt": int(time.time() * 1000),
    }
    rows.append(new_word)
    rows = sort_words(rows)
    out = {"words": rows} if isinstance(data, dict) else rows
    message = f"vocab: 添加单词 {word}（{current_user.username}）"
    try:
        saved = await content_store.write_text(
            VOCAB_REL_PATH,
            json.dumps(out, ensure_ascii=False, indent=2) + "\n",
            message,
            sha=snap["sha"],
        )
    except ContentError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    await feed.apply_words(normalize_words(out))
    return {**new_word, "commit_url": saved.get("commit_url")}


class WordDelete(BaseModel):
    word: str = Field(..., min_length=1, max_length=100)


@router.delete("/api/v1/vocabulary")
async def delete_word(payload: WordDelete, request: Request,
                      current_user: User = Depends(get_current_user)):
    """登录用户删除单词：从仓库 JSON 中移除并立即刷新内存快照。"""
    vocab_write_limiter.limit(request, key=f"user:{current_user.id}")
    word = payload.word.strip()
    if not word:
        raise HTTPException(status_code=422, detail="单词不能为空")
    try:
        snap = await content_store.read_text(VOCAB_REL_PATH)
    except ContentError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    try:
        data = json.loads(snap["content"])
    except ValueError:
        raise HTTPException(status_code=500, detail="单词清单格式异常，请联系站点维护者")
    rows = data.get("words") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise HTTPException(status_code=500, detail="单词清单格式异常，请联系站点维护者")
    key = word.casefold()
    remaining = [r for r in rows
                 if not (isinstance(r, dict) and str(r.get("word", "")).strip().casefold() == key)]
    if len(remaining) == len(rows):
        raise HTTPException(status_code=404, detail=f"单词「{word}」不在记录中")
    removed = next(r for r in rows
                   if isinstance(r, dict) and str(r.get("word", "")).strip().casefold() == key)
    out = {"words": sort_words(remaining)} if isinstance(data, dict) else sort_words(remaining)
    message = f"vocab: 删除单词 {str(removed.get('word') or word)}（{current_user.username}）"
    try:
        saved = await content_store.write_text(
            VOCAB_REL_PATH,
            json.dumps(out, ensure_ascii=False, indent=2) + "\n",
            message,
            sha=snap["sha"],
        )
    except ContentError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    await feed.apply_words(normalize_words(out))
    return {**removed, "deleted": True, "commit_url": saved.get("commit_url")}
