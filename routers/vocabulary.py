"""Read-only GitHub vocabulary feed, shared by all website visitors."""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(tags=["vocabulary"])
BASE_DIR = Path(__file__).resolve().parent.parent
REPO = "hanjiongmin-stack/chongyue-jianyuan"
BRANCH = os.environ.get("CYJY_VOCAB_BRANCH", "main")
DATA_PATH = os.environ.get("CYJY_VOCAB_PATH", "content/ielts-words.json")
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


feed = VocabularyFeed()


@router.get("/ielts", response_class=HTMLResponse)
async def vocabulary_page():
    return HTMLResponse((BASE_DIR / "static" / "ielts.html").read_text(encoding="utf-8"))


@router.get("/api/v1/vocabulary")
async def vocabulary_data():
    data = await feed.snapshot()
    return JSONResponse(data, status_code=200 if data["available"] else 503,
                        headers={"Cache-Control": "no-store"})
