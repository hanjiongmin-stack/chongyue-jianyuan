"""Read-only GitHub vocabulary feed, shared by all website visitors."""

import asyncio
import json
import os
import re
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


# ── 自动查词：只填单词，音标和中文释义由服务端查好 ──────────────
LOOKUP_CACHE = {}
LOOKUP_CACHE_TTL = 24 * 3600
LOOKUP_CACHE_MAX = 2000
# 查词会打外部接口：单 IP 每分钟最多 30 次
vocab_lookup_limiter = RateLimiter(max_requests=30, window_seconds=60)
WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'\- ]{0,99}$")
ICIBA_URL = "https://dict-mobile.iciba.com/interface/index.php"
DICT_API_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/"
WIKTIONARY_URL = "https://en.wiktionary.org/w/index.php"
LOOKUP_UA = "ChongYue-JianYuan-Vocabulary/1.0"


def _cache_get(key):
    hit = LOOKUP_CACHE.get(key)
    if hit and time.time() - hit[0] < LOOKUP_CACHE_TTL:
        return hit[1]
    LOOKUP_CACHE.pop(key, None)
    return None


def _cache_put(key, value):
    if len(LOOKUP_CACHE) > LOOKUP_CACHE_MAX:
        LOOKUP_CACHE.clear()
    LOOKUP_CACHE[key] = (time.time(), value)


def _clean_phonetic(text):
    text = (text or "").strip()
    if not text:
        return ""
    if not text.startswith("/"):
        text = "/" + text
    if not text.endswith("/"):
        text += "/"
    return text[:200]


async def _iciba_zh(word, client):
    """金山词霸：返回带词性的中文释义，如 adj. 有韧性的；适应力强的。"""
    try:
        r = await client.get(ICIBA_URL, params={"c": "word", "m": "getsuggest",
                                                "is_need_mean": "1", "word": word})
        if r.status_code != 200:
            return ""
        rows = (r.json() or {}).get("message") or []
    except Exception:
        return ""
    if not isinstance(rows, list):
        return ""
    target = word.casefold()
    entry = next((row for row in rows if isinstance(row, dict)
                  and str(row.get("key", "")).strip().casefold() == target), None)
    entry = entry or next((row for row in rows if isinstance(row, dict) and row.get("means")), None)
    if not entry:
        return ""
    groups = entry.get("means") or []
    parts = []
    for group in groups[:3]:
        if not isinstance(group, dict):
            continue
        means = [str(m).strip() for m in (group.get("means") or []) if str(m).strip()]
        if not means:
            continue
        part = str(group.get("part") or "").strip()
        parts.append((part + " " + "；".join(means[:3])).strip())
    zh = "；".join(parts)
    return zh[:1000]


async def _phonetic_from_dictionary_api(word, client):
    try:
        r = await client.get(DICT_API_URL + quote(word, safe=""))
        if r.status_code != 200:
            return ""
        entries = r.json()
        if not isinstance(entries, list):
            return ""
        for entry in entries:
            for item in (entry.get("phonetics") or []):
                text = str(item.get("text") or "").strip()
                if text:
                    return _clean_phonetic(text)
    except Exception:
        return ""
    return ""


async def _zh_from_youdao(word, client):
    """有道：金山词霸查不到时的备用中文释义（同样带词性）。"""
    try:
        r = await client.get("https://dict.youdao.com/suggest",
                             params={"q": word, "doctype": "json", "num": "1", "ver": "3.0"})
        if r.status_code != 200:
            return ""
        entries = ((r.json() or {}).get("data") or {}).get("entries") or []
        for entry in entries:
            explain = str(entry.get("explain") or "").strip()
            if explain:
                return explain[:1000]
    except Exception:
        return ""
    return ""


BING_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


async def _phonetic_from_bing(word, client):
    """Bing 词典：取美式音标，没有再取英式；两个域名都试一遍。"""
    for host in ("https://cn.bing.com/dict/search", "https://www.bing.com/dict/search"):
        try:
            r = await client.get(host, params={"q": word, "mkt": "en-US"},
                                 headers={"User-Agent": BING_UA,
                                          "Accept-Language": "en-US,en;q=0.9"})
            if r.status_code != 200:
                continue
            html = r.text
        except Exception:
            continue
        # 页面里形如「美&nbsp;[ˌfoʊtoʊˈsɪnθəsɪs]」「英国&nbsp;[ˌfəʊtəʊˈsɪnθəsɪs]」
        for pattern in (r"美\s*(?:&#160;|&nbsp;)?\s*\[([^\]]{1,60})\]",
                        r"英\s*(?:&#160;|&nbsp;)?\s*\[([^\]]{1,60})\]"):
            match = re.search(pattern, html)
            if match:
                text = match.group(1).replace("&#160;", " ").strip()
                if re.fullmatch(r"[\wˈˌː.əɪʊʌæɑɒɔɜθðʃʒŋɡɹɐɵʁ() ‐-]+", text):
                    return _clean_phonetic(text)
    return ""


async def _phonetic_from_wiktionary(word, client):
    try:
        r = await client.get(WIKTIONARY_URL, params={"title": word, "action": "raw"})
        if r.status_code != 200:
            return ""
        match = re.search(r"\{\{IPA\|en\|([^}|]+)", r.text)
        # Wiktionary 用 ɹ 表示英语的 r，换成常见的 r 更好认
        return _clean_phonetic(match.group(1).replace("ɹ", "r")) if match else ""
    except Exception:
        return ""
    return ""


async def lookup_word_info(word):
    """查单词的音标与中文释义；查不到就返回空字符串，绝不抛异常。"""
    key = word.casefold()
    cached = _cache_get(key)
    if cached is not None:
        return {**cached, "cached": True}
    result = {"word": word, "phonetic": "", "zh": "", "sources": []}
    zh_source = phonetic_source = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), headers={"User-Agent": LOOKUP_UA},
                                     follow_redirects=True) as client:
            zh = await _iciba_zh(word, client)
            if zh:
                zh_source = "iciba"
            else:
                zh = await _zh_from_youdao(word, client)
                zh_source = "youdao" if zh else ""
            phonetic = await _phonetic_from_dictionary_api(word, client)
            phonetic_source = "dictionaryapi.dev" if phonetic else ""
            if not phonetic:
                phonetic = await _phonetic_from_bing(word, client)
                phonetic_source = "bing" if phonetic else ""
            if not phonetic:
                phonetic = await _phonetic_from_wiktionary(word, client)
                phonetic_source = "wiktionary" if phonetic else ""
    except Exception:
        zh = phonetic = ""
    result["zh"] = zh or ""
    result["phonetic"] = phonetic or ""
    result["sources"] = [name for name in (zh_source, phonetic_source) if name]
    _cache_put(key, result)
    return result


@router.get("/api/v1/vocabulary/lookup")
async def lookup_word(request: Request, word: str = Query(default="", max_length=100)):
    """只输入单词时，前端用它预览自动查到的音标与中文释义。"""
    vocab_lookup_limiter.limit(request)
    word = word.strip()
    if not word:
        raise HTTPException(status_code=422, detail="请填写要查询的单词")
    if not WORD_RE.match(word):
        raise HTTPException(status_code=422, detail="请填写英文字母组成的单词")
    return await lookup_word_info(word)


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
    # 只填了单词时：服务端自动查音标和中文释义，查不到也不影响保存
    if (not phonetic or not zh) and WORD_RE.match(word):
        try:
            found = await lookup_word_info(word)
            phonetic = phonetic or found.get("phonetic", "")
            zh = zh or found.get("zh", "")
        except Exception:
            pass
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
