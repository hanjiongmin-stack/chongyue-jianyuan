#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
崇岳鉴渊 - 统一入口服务器 (FastAPI + 反向代理)
==============================================
功能:
  1. 提供静态首页 optimus.html ( / )
  2. 代理数学竞赛系统 ( /math/* /pdf/* /api/* -> 127.0.0.1:8088 )
  3. 请求日志与错误日志 ( logs/ )
  4. 全局异常处理，不暴露 Traceback
==============================================
启动: python unified_server.py
监听: 0.0.0.0:8888
"""

import os
import re
import gzip
import sys
import hashlib
import inspect
import logging
import asyncio
from pathlib import Path
from datetime import datetime

# ── Auto-load .env into os.environ (before any module reads env vars) ──
_ENV_PATH = Path(__file__).resolve().parent / ".env"
if _ENV_PATH.exists():
    with open(_ENV_PATH, "r", encoding="utf-8") as _f:
        for _raw in _f:
            _ln = _raw.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                _k, _v = _ln.split("=", 1)
                _k = _k.strip()
                _v = _v.strip().strip('"').strip("'")
                if _k and _k not in os.environ:
                    os.environ[_k] = _v

from contextlib import asynccontextmanager
import urllib.request
import urllib.error

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ── Database & API Routers ──────────────────────────
from security import (
    SecurityHeadersMiddleware,
    auth_limiter,
    ai_limiter,
    upload_limiter,
)

from database import init_db
from routers.categories import router as categories_router
from routers.resources import router as resources_router
from routers.tags import router as tags_router
from routers.auth import router as auth_router
from routers.users import router as users_router
from routers.ai import router as ai_router
from routers.admin import router as admin_router
from routers.elite import router as elite_router

# ============================================================
# 路径配置 - 禁止硬编码，基于本文件位置自动推导
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# ============================================================
# 后端数学竞赛服务器地址
# ============================================================
BACKEND_URL = os.environ.get("CYJY_BACKEND_URL", "http://127.0.0.1:8088")

# ============================================================
# 日志系统 - 同时输出到文件和控制台
# ============================================================
file_handler = logging.FileHandler(
    LOGS_DIR / f"server_{datetime.now().strftime('%Y%m%d')}.log",
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
))
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
))
console_handler.setLevel(logging.INFO)

logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])
logger = logging.getLogger("unified_server")
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# ============================================================
# FastAPI 生命周期 - 管理 httpx 客户端连接池
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时的生命周期管理"""
    # 确保上传目录存在（Render 等云端环境 git clone 不含空目录）
    uploads_dir = STATIC_DIR / "uploads"
    uploads_dir.mkdir(exist_ok=True)

    init_db()
    logger.info("数据库已初始化")
    logger.info("统一入口服务器启动完成")
    yield
    if _math_http is not None:
        await _math_http.aclose()
    logger.info("统一入口服务器正在关闭")


# ============================================================
# FastAPI 应用实例
# ============================================================
app = FastAPI(
    title="崇岳鉴渊",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

# CORS -- whitelist mode (configurable via CYJY_CORS_ORIGINS env)
CORS_ORIGINS = os.environ.get(
    "CYJY_CORS_ORIGINS",
    "http://localhost:8888,http://127.0.0.1:8888,http://localhost:3000,http://localhost:5173,https://chongyue-jianyuan.onrender.com"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in CORS_ORIGINS if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# GZip 压缩中间件（减少 HTML/JSON 传输体积 60-80%）
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
_gzip_kwargs = {"minimum_size": 500}
# PDF / 压缩包本身已压缩，再 gzip 只会拖慢并让 PDF.js 无法分段加载（新版 Starlette 才支持该参数）
if "exclude_content_types" in inspect.signature(GZipMiddleware.__init__).parameters:
    from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES
    _gzip_kwargs["exclude_content_types"] = tuple(DEFAULT_EXCLUDED_CONTENT_TYPES) + (
        "application/pdf", "application/wasm", "application/octet-stream",
        "application/x-rar-compressed", "application/vnd.rar", "application/x-7z-compressed",
    )
app.add_middleware(GZipMiddleware, **_gzip_kwargs)


# ── 页面公共片段（导航 / 页脚 / AI 助手）──────────────────
# 页面中的 <!--cy:名称--> 会被替换为 static/partials/名称.html，
# 片段里的 %%V%% 替换为静态资源内容哈希，用于绕过 /assets 的长缓存。
_PARTIALS_DIR = STATIC_DIR / "partials"
_PARTIAL_RE = re.compile(r"<!--cy:([a-z0-9-]+)-->")
_partial_cache: dict = {}
_asset_version_cache: dict = {}


def _asset_version() -> str:
    files = [STATIC_DIR / "assets" / "cyjy.css", STATIC_DIR / "assets" / "cyjy.js"]
    try:
        key = tuple(f.stat().st_mtime_ns for f in files)
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


def _apply_partials(body: str) -> str:
    if "<!--cy:" not in body:
        return body
    version = _asset_version()
    return _PARTIAL_RE.sub(lambda m: _partial(m.group(1)).replace("%%V%%", version), body)


# ── SEO + 缓存中间件 ───────────────────────────────────
# 自动给所有 HTML 响应注入 meta 标签，给静态资源加缓存头
class _SEOInjectMiddleware(BaseHTTPMiddleware):
    """自动为 HTML 响应注入 meta description / OG 标签 / 缓存头。"""

    SITE_NAME = "崇岳鉴渊"
    SITE_URL = "https://chongyue-jianyuan.onrender.com"
    DEFAULT_DESC = "大学生科研互助与学习资源共享平台——数学竞赛真题库、AI编程、多维知识库、科研孵化、高等化学资料一站汇聚"

    PAGE_META = {
        "/": {
            "title": "崇岳鉴渊 — 大学生学术与编程进阶平台",
            "desc": "面向高能大学生的科研互助与学习资源共享平台。数学竞赛真题库、AI编程专区、多维知识库、科研孵化、高等化学资料一站汇聚。",
        },
        "/knowledge": {
            "title": "学习资源库 — 崇岳鉴渊",
            "desc": "公共基础课、专业核心课、学科竞赛、论文写作、升学备考、工具素材——分类浏览，标签筛选，全文搜索。",
        },
        "/login": {
            "title": "登录 — 崇岳鉴渊",
            "desc": "登录崇岳鉴渊，收藏学习资源、标记学习进度、加入科研孵化圈。",
        },
        "/profile": {
            "title": "个人中心 — 崇岳鉴渊",
            "desc": "管理个人信息、查看收藏与学习进度、修改密码。",
        },
        "/ai-coding": {
            "title": "AI 编程专区 — 崇岳鉴渊",
            "desc": "Claude Code 工作流、Cursor 前端实战、Prompt 工程——AI 编程教学与工程脚手架。",
        },
        "/research": {
            "title": "科研孵化 — 崇岳鉴渊",
            "desc": "开源项目共建、PR 贡献指南、论文复现、实验室对接——从入门到产出。",
        },
        "/math": {
            "title": "数学竞赛真题库 — 崇岳鉴渊",
            "desc": "全国大学生数学竞赛（CMC）/ 美赛（MCM/ICM）历年真题与特等奖论文，529个文件，20个年份。",
        },
        "/pricing": {
            "title": "平台通道 — 崇岳鉴渊",
            "desc": "免费新手池、进阶舱、科研孵化圈——选择适合你的学习计划。",
        },
        "/knowledge-base": {
            "title": "多维溯熵知识库 — 崇岳鉴渊",
            "desc": "计算机、高等数学、数据科学、高等化学等核心专业课的高分笔记与课后全解，学长学姐开源共建。",
        },
        "/math-hub": {
            "title": "高等数学 — 崇岳鉴渊",
            "desc": "微积分、线性代数、概率论三大分支，粒子交互演示直观理解抽象概念。",
        },
        "/signals-and-systems": {
            "title": "信号与系统 — 崇岳鉴渊",
            "desc": "时域、频域、离散域 8 大模块交互推导：卷积、傅里叶级数与变换、拉普拉斯变换、Z 变换、采样与滤波。",
        },
        "/chemistry": {
            "title": "高等化学知识库 — 崇岳鉴渊",
            "desc": "有机、无机、物理化学、分析化学、生物化学五大分支的完整理论体系与习题精练。",
        },
        "/python-course": {
            "title": "Python 数据分析 — 崇岳鉴渊",
            "desc": "从成绩计算器到房价预测、鸢尾花分类，8 个实战项目搭建你的数据分析作品集。",
        },
    }

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        content_type = response.headers.get("content-type", "")
        path = request.url.path.rstrip("/") or "/"

        # ── 静态资源缓存 ──
        if path.startswith("/assets/") or path.startswith("/uploads/"):
            response.headers["Cache-Control"] = "public, max-age=604800, immutable"

        # ── HTML 注入 SEO ──
        if "text/html" in content_type and response.status_code == 200:
            meta = self.PAGE_META.get(path, {
                "title": self.SITE_NAME,
                "desc": self.DEFAULT_DESC,
            })
            og_tags = (
                f'<meta name="description" content="{meta["desc"]}">\n'
                f'<meta property="og:title" content="{meta["title"]}">\n'
                f'<meta property="og:description" content="{meta["desc"]}">\n'
                f'<meta property="og:type" content="website">\n'
                f'<meta property="og:url" content="{self.SITE_URL}{path}">\n'
                f'<meta property="og:site_name" content="{self.SITE_NAME}">\n'
                f'<meta name="twitter:card" content="summary">\n'
            )
            # call_next 返回的是流式响应（没有 .body），且内层 GZip 可能已压缩正文
            raw = b"".join([chunk async for chunk in response.body_iterator])
            encoding = response.headers.get("content-encoding", "")
            out = raw
            try:
                data = gzip.decompress(raw) if encoding == "gzip" else raw
                body = _apply_partials(data.decode("utf-8"))
                if "<head>" in body:
                    body = body.replace("<head>", "<head>\n" + og_tags, 1)
                if "<title>" not in body and "</head>" in body:
                    body = body.replace("</head>", f"<title>{meta['title']}</title>\n</head>", 1)
                out = body.encode("utf-8")
                if encoding == "gzip":
                    out = gzip.compress(out, compresslevel=6)
            except Exception:
                out = raw
            headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
            response = Response(content=out, status_code=response.status_code, headers=headers)

        return response


app.add_middleware(_SEOInjectMiddleware)


# ── HEAD 请求支持（UptimeRobot 免费版只发 HEAD） ──────────
# Starlette 的 @app.get() 装饰器默认只匹配 GET，对 HEAD 返回 405。
# 此 ASGI 中间件在路由匹配前将 HEAD 转为 GET，并清空响应体。
class _HeadSupportMiddleware:
    """ASGI middleware: transparently converts HEAD requests to GET and strips body."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "HEAD":
            scope["method"] = "GET"

            async def _strip_body(message):
                if message["type"] == "http.response.body":
                    message = dict(message, body=b"")
                await send(message)

            await self.app(scope, receive, _strip_body)
        else:
            await self.app(scope, receive, send)


app.add_middleware(_HeadSupportMiddleware)

# ============================================================
# 静态文件挂载
# ============================================================
# Windows 注册表可能把 .js/.mjs 映射成 text/plain，导致浏览器拒绝执行模块脚本
import mimetypes
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/css", ".css")

assets_dir = STATIC_DIR / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    logger.info(f"静态资源已挂载: {assets_dir}")

uploads_dir = STATIC_DIR / "uploads"
if uploads_dir.exists():
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")
    logger.info(f"上传文件已挂载: {uploads_dir}")
else:
    logger.warning(f"上传目录不存在: {uploads_dir}")
if not assets_dir.exists():
    logger.warning(f"静态资源目录不存在: {assets_dir}")


# ============================================================
# 页面路由
# ============================================================

# 首页 - / -> static/index.html
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """返回首页（崇岳鉴渊落地页）"""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        logger.error(f"首页文件不存在: {index_path}")
        return HTMLResponse(
            content=get_error_page("首页文件未找到", "请确认 static/index.html 存在"),
            status_code=200,
        )
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/knowledge", response_class=HTMLResponse)
async def serve_knowledge():
    """返回知识资源列表页"""
    knowledge_path = STATIC_DIR / "knowledge.html"
    if not knowledge_path.exists():
        logger.error(f"知识资源页不存在: {knowledge_path}")
        return HTMLResponse(
            content=get_error_page("页面未找到", "请确认 static/knowledge.html 存在"),
            status_code=200,
        )
    return HTMLResponse(knowledge_path.read_text(encoding="utf-8"))


@app.get("/knowledge/{resource_id}", response_class=HTMLResponse)
async def serve_knowledge_detail(resource_id: int):
    """返回知识资源详情页"""
    detail_path = STATIC_DIR / "knowledge-detail.html"
    if not detail_path.exists():
        return HTMLResponse(
            content=get_error_page("页面未找到", "请确认 static/knowledge-detail.html 存在"),
            status_code=200,
        )
    return HTMLResponse(detail_path.read_text(encoding="utf-8"))


@app.get("/login", response_class=HTMLResponse)
async def serve_login():
    """返回登录/注册页"""
    login_path = STATIC_DIR / "login.html"
    if not login_path.exists():
        logger.error(f"登录页不存在: {login_path}")
        return HTMLResponse(
            content=get_error_page("页面未找到", "请确认 static/login.html 存在"),
            status_code=200,
        )
    return HTMLResponse(login_path.read_text(encoding="utf-8"))


@app.get("/knowledge-base", response_class=HTMLResponse)
async def serve_knowledge_base():
    """返回多维知识库页"""
    kb_path = STATIC_DIR / "knowledge-base.html"
    if not kb_path.exists():
        return HTMLResponse(content=get_error_page("页面未找到", "knowledge-base.html"), status_code=200)
    return HTMLResponse(kb_path.read_text(encoding="utf-8"))


@app.get("/math-hub", response_class=HTMLResponse)
async def serve_math_hub():
    """返回高等数学知识库页"""
    mh = STATIC_DIR / "math-hub.html"
    if not mh.exists():
        return HTMLResponse(content=get_error_page("页面未找到", "math-hub.html"), status_code=200)
    return HTMLResponse(mh.read_text(encoding="utf-8"))


@app.get("/signals-and-systems", response_class=HTMLResponse)
async def serve_signals_and_systems():
    """返回信号与系统知识库页"""
    sp = STATIC_DIR / "signals-and-systems.html"
    if not sp.exists():
        return HTMLResponse(content=get_error_page("页面未找到", "signals-and-systems.html"), status_code=200)
    return HTMLResponse(sp.read_text(encoding="utf-8"))


@app.get("/research", response_class=HTMLResponse)
async def serve_research():
    """返回科研孵化页"""
    rp = STATIC_DIR / "research.html"
    if not rp.exists():
        return HTMLResponse(content=get_error_page("页面未找到", "research.html"), status_code=200)
    return HTMLResponse(rp.read_text(encoding="utf-8"))


@app.get("/profile", response_class=HTMLResponse)
async def serve_profile():
    p = STATIC_DIR / "profile.html"
    if not p.exists(): return HTMLResponse(content=get_error_page("页面未找到", "profile.html"), status_code=200)
    return HTMLResponse(p.read_text(encoding="utf-8"))


@app.get("/pricing", response_class=HTMLResponse)
async def serve_pricing():
    p = STATIC_DIR / "pricing.html"
    if not p.exists(): return HTMLResponse(content=get_error_page("页面未找到", "pricing.html"), status_code=200)
    return HTMLResponse(p.read_text(encoding="utf-8"))

@app.get("/pricing/start", response_class=HTMLResponse)
async def serve_pricing_start():
    p = STATIC_DIR / "pricing-start.html"
    if not p.exists(): return HTMLResponse(content=get_error_page("页面未找到", "pricing-start.html"), status_code=200)
    return HTMLResponse(p.read_text(encoding="utf-8"))

@app.get("/pricing/pro", response_class=HTMLResponse)
async def serve_pricing_pro():
    p = STATIC_DIR / "pricing-pro.html"
    if not p.exists(): return HTMLResponse(content=get_error_page("页面未找到", "pricing-pro.html"), status_code=200)
    return HTMLResponse(p.read_text(encoding="utf-8"))

@app.get("/pricing/elite", response_class=HTMLResponse)
async def serve_pricing_elite():
    p = STATIC_DIR / "pricing-elite.html"
    if not p.exists(): return HTMLResponse(content=get_error_page("页面未找到", "pricing-elite.html"), status_code=200)
    return HTMLResponse(p.read_text(encoding="utf-8"))

@app.get("/pricing/partner", response_class=HTMLResponse)
async def serve_pricing_partner():
    p = STATIC_DIR / "pricing-partner.html"
    if not p.exists(): return HTMLResponse(content=get_error_page("页面未找到", "pricing-partner.html"), status_code=200)
    return HTMLResponse(p.read_text(encoding="utf-8"))

@app.get("/elite-matrix", response_class=HTMLResponse)
async def serve_elite_matrix():
    """精英矩阵 - 星辰科研孵化圈成员专属页面"""
    p = STATIC_DIR / "elite-matrix.html"
    if not p.exists(): return HTMLResponse(content=get_error_page("页面未找到", "elite-matrix.html"), status_code=200)
    return HTMLResponse(p.read_text(encoding="utf-8"))

@app.get("/admin-elite", response_class=HTMLResponse)
async def serve_admin_elite():
    """精英矩阵审批管理面板（仅管理员）"""
    p = STATIC_DIR / "admin-elite.html"
    if not p.exists(): return HTMLResponse(content=get_error_page("页面未找到", "admin-elite.html"), status_code=200)
    return HTMLResponse(p.read_text(encoding="utf-8"))


@app.get("/ai-coding", response_class=HTMLResponse)
async def serve_ai_coding():
    """返回AI编程专区页"""
    ai_path = STATIC_DIR / "ai-coding.html"
    if not ai_path.exists():
        logger.error(f"AI编程页不存在: {ai_path}")
        return HTMLResponse(
            content=get_error_page("页面未找到", "请确认 static/ai-coding.html 存在"),
            status_code=200,
        )
    return HTMLResponse(ai_path.read_text(encoding="utf-8"))


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin():
    """管理后台"""
    return HTMLResponse(content=ADMIN_HTML)


@app.get("/python-course", response_class=HTMLResponse)
async def serve_python_course():
    """返回Python数据分析课程页（像素AI风格）"""
    path = STATIC_DIR / "python-course.html"
    if not path.exists():
        return HTMLResponse(content=get_error_page("页面未找到", "python-course.html"), status_code=200)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/testimonials", response_class=HTMLResponse)
async def serve_testimonials():
    """返回客户评价页（赛博朋克风格轮播）"""
    path = STATIC_DIR / "testimonials.html"
    if not path.exists():
        return HTMLResponse(content=get_error_page("页面未找到", "testimonials.html"), status_code=200)
    return HTMLResponse(path.read_text(encoding="utf-8"))


# ============================================================
# GitHub API 代理（带内存缓存，解决 Rate Limit 问题）
# ============================================================
import json as _json
import time as _time

_gh_cache = {}
_GH_CACHE_TTL = 3600  # 热门项目缓存1小时
_GH_SEARCH_TTL = 600   # 搜索结果缓存10分钟


@app.get("/api/v1/github/{path:path}")
async def github_proxy(path: str, request: Request):
    """代理 GitHub API 请求，带内存缓存。"""
    # 构建目标URL
    target = f"https://api.github.com/{path}"
    if request.url.query:
        target += f"?{request.url.query}"

    # 检查缓存
    cache_key = target
    now = _time.time()
    if cache_key in _gh_cache:
        cached_data, cached_at = _gh_cache[cache_key]
        ttl = _GH_SEARCH_TTL if "/search/" in target else _GH_CACHE_TTL
        if now - cached_at < ttl:
            return cached_data

    # 发起请求
    try:
        req = urllib.request.Request(target)
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "ChongYue-JianYuan/1.0")
        # 如果有 GitHub Token，使用认证请求（更高的 Rate Limit）
        gh_token = os.environ.get("GITHUB_TOKEN", "")
        if gh_token:
            req.add_header("Authorization", f"Bearer {gh_token}")

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if hasattr(e, "read") else "{}"
        try:
            data = _json.loads(error_body)
        except:
            data = {"error": "GitHub API error", "status": e.code}
        if e.code == 403 and "rate limit" in error_body.lower():
            # Rate limited — 返回缓存数据如果有的话
            if cache_key in _gh_cache:
                cached_data, _ = _gh_cache[cache_key]
                return cached_data
    except Exception as e:
        # 网络错误 — 返回缓存
        if cache_key in _gh_cache:
            cached_data, _ = _gh_cache[cache_key]
            return cached_data
        return {"error": str(e), "status": 502}

    # 存入缓存
    _gh_cache[cache_key] = (data, now)

    # 定期清理过期缓存（每100次请求清理一次）
    if len(_gh_cache) > 100:
        expired = [k for k, (_, t) in _gh_cache.items() if now - t > _GH_CACHE_TTL * 2]
        for k in expired:
            del _gh_cache[k]

    return data


# ============================================================
# 错误页面模板
# ============================================================
def get_error_page(title: str, detail: str) -> str:
    """生成统一风格的错误页面 HTML"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - 崇岳鉴渊</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: "Instrument Sans", system-ui, -apple-system, sans-serif;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    background: #fbfbfa;
    color: #1a1a18;
  }}
  .box {{
    text-align: center;
    max-width: 500px;
    padding: 3rem 2rem;
  }}
  h1 {{
    font-size: 1.5rem;
    font-weight: 500;
    margin-bottom: 1rem;
    letter-spacing: -0.01em;
  }}
  p {{
    color: #6b6b66;
    line-height: 1.7;
    margin-bottom: 0.5rem;
    font-size: 0.9375rem;
  }}
  a {{
    color: #1a1a18;
    text-underline-offset: 4px;
  }}
  .back-link {{
    display: inline-block;
    margin-top: 2rem;
    font-size: 0.875rem;
  }}
  code {{
    font-family: "JetBrains Mono", monospace;
    font-size: 0.8125rem;
    background: rgba(26,26,24,0.05);
    padding: 0.125rem 0.5rem;
    border-radius: 4px;
  }}
</style>
</head>
<body>
<div class="box">
  <h1>{title}</h1>
  <p>{detail}</p>
  <a href="/" class="back-link">&larr; 返回首页</a>
</div>
</body>
</html>"""


# ============================================================
# 管理后台页面
# ============================================================
ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>管理后台 — 崇岳鉴渊</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"Instrument Sans","Microsoft YaHei",sans-serif;background:#fbfbfa;color:#1a1a18;padding:2rem}
h1{font-size:1.4rem;font-weight:500;margin-bottom:1.5rem}
.toolbar{display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap}
.toolbar button,.toolbar input{padding:.4rem .8rem;border:1px solid #ddd;border-radius:4px;font-size:.8125rem;cursor:pointer;background:#fff}
.toolbar button:hover{background:#f0f0f0}
table{width:100%;border-collapse:collapse;font-size:.8125rem}
th,td{padding:.5rem .75rem;text-align:left;border-bottom:1px solid rgba(26,26,24,.08)}
th{font-weight:500;color:#6b6b66;position:sticky;top:0;background:#fbfbfa}
tr:hover{background:rgba(26,26,24,.02)}
.badge{padding:1px 8px;border-radius:10px;font-size:.6875rem;font-weight:500}
.badge-free{background:#e8e8e8;color:#666}
.badge-start{background:#e3f2fd;color:#1565c0}
.badge-pro{background:#f3e5f5;color:#7b1fa2}
.badge-elite{background:#fff3e0;color:#e65100}
.badge-active{background:#e8f5e9;color:#2e7d32}
.badge-inactive{background:#ffebee;color:#c62828}
.badge-elite-yes{background:#ffecb3;color:#f57f17}
.btn-sm{padding:2px 8px;border:1px solid #ddd;border-radius:3px;font-size:.6875rem;cursor:pointer;background:#fff;margin:1px}
.btn-sm:hover{background:#f0f0f0}
.btn-sm.danger{color:#c62828;border-color:#ffcdd2}
.btn-sm.danger:hover{background:#ffebee}
.modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.3);z-index:100;justify-content:center;align-items:center}
.modal.show{display:flex}
.modal-box{background:#fff;border-radius:8px;padding:1.5rem;min-width:320px;max-width:400px;box-shadow:0 4px 24px rgba(0,0,0,.15)}
.modal-box h3{margin-bottom:1rem;font-size:1rem}
.modal-box label{display:block;font-size:.75rem;color:#6b6b66;margin:.5rem 0 .25rem}
.modal-box select,.modal-box input[type=text],.modal-box input[type=date],.modal-box input[type=password]{width:100%;padding:.4rem .5rem;border:1px solid #ddd;border-radius:4px;font-size:.8125rem}
.modal-box .actions{display:flex;gap:.5rem;margin-top:1rem;justify-content:flex-end}
.modal-box .actions button{padding:.4rem 1rem;border-radius:4px;border:1px solid #ddd;cursor:pointer;font-size:.8125rem}
.modal-box .actions .primary{background:#1a1a18;color:#fff;border:none}
.toast{position:fixed;bottom:2rem;right:2rem;background:#1a1a18;color:#fff;padding:.75rem 1.25rem;border-radius:6px;font-size:.8125rem;z-index:200;opacity:0;transition:opacity .3s}
.toast.show{opacity:1}
</style>
</head>
<body>
<h1>🔧 管理后台</h1>
<div class="toolbar">
  <button onclick="loadUsers()">🔄 刷新</button>
  <input type="text" id="searchBox" placeholder="搜索用户名/邮箱..." oninput="filterTable()" style="width:200px">
  <span style="font-size:.75rem;color:#6b6b66;margin-left:auto" id="userCount"></span>
</div>
<table>
  <thead>
    <tr>
      <th>ID</th><th>用户名</th><th>邮箱</th><th>订阅</th><th>精英矩阵</th><th>状态</th><th>注册时间</th><th>操作</th>
    </tr>
  </thead>
  <tbody id="userTable"></tbody>
</table>

<!-- 编辑弹窗 -->
<div class="modal" id="editModal">
  <div class="modal-box">
    <h3>编辑用户 <span id="editUsername"></span></h3>
    <input type="hidden" id="editUserId">
    <label>订阅方案</label>
    <select id="editSubscription">
      <option value="free">免费</option><option value="start">新手池</option><option value="pro">进阶舱</option><option value="elite">科研孵化圈</option>
    </select>
    <label>订阅到期</label>
    <input type="date" id="editExpires">
    <label>精英矩阵</label>
    <select id="editElite"><option value="0">否</option><option value="1">是</option></select>
    <label>账号状态</label>
    <select id="editActive"><option value="1">启用</option><option value="0">禁用</option></select>
    <div class="actions">
      <button onclick="closeEdit()">取消</button>
      <button class="primary" onclick="saveUser()">保存</button>
    </div>
  </div>
</div>

<!-- 重置密码弹窗 -->
<div class="modal" id="pwdModal">
  <div class="modal-box">
    <h3>重置密码 <span id="pwdUsername"></span></h3>
    <input type="hidden" id="pwdUserId">
    <label>新密码（至少6位）</label>
    <input type="password" id="newPassword" placeholder="输入新密码">
    <div class="actions">
      <button onclick="closePwd()">取消</button>
      <button class="primary" onclick="resetPwd()">确认重置</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const API = '/api/v1/admin';
let token = '';

// 从 localStorage 读取 token
(function(){ token = localStorage.getItem('cyjy_access_token') || ''; if(!token){ document.body.innerHTML='<div style="text-align:center;padding:4rem"><h2>请先登录</h2><p style="color:#6b6b66;margin:1rem 0">需要管理员账号</p><a href="/login">去登录</a></div>'; } else { loadUsers(); } })();

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(API + path, opts);
  if (r.status === 403) { toast('需要管理员权限'); return null; }
  if (r.status === 401) { toast('登录已过期，请重新登录'); localStorage.removeItem('cyjy_access_token'); setTimeout(()=>location.href='/login',1500); return null; }
  if (!r.ok) { const e = await r.json().catch(()=>({})); toast(e.detail || '操作失败'); return null; }
  return r.json();
}

async function loadUsers() {
  const data = await api('GET', '/users');
  if (!data) return;
  const tbody = document.getElementById('userTable');
  const labels = {free:'免费',start:'新手池',pro:'进阶舱',elite:'孵化圈'};
  const badgeClass = {free:'badge-free',start:'badge-start',pro:'badge-pro',elite:'badge-elite'};
  tbody.innerHTML = data.map(u => `
    <tr data-search="${u.username} ${u.email} ${u.display_name}">
      <td>${u.id}</td>
      <td><strong>${esc(u.username)}</strong>${u.is_admin?' <span style="font-size:.625rem;color:#e65100">[管理]</span>':''}</td>
      <td style="color:#6b6b66">${esc(u.email)}</td>
      <td><span class="badge ${badgeClass[u.subscription]||'badge-free'}">${labels[u.subscription]||u.subscription}</span></td>
      <td>${u.is_elite?'<span class="badge badge-elite-yes">精英</span>':'—'}</td>
      <td>${u.is_active?'<span class="badge badge-active">启用</span>':'<span class="badge badge-inactive">禁用</span>'}</td>
      <td style="font-size:.6875rem;color:#999">${(u.created_at||'').slice(0,10)}</td>
      <td>
        <button class="btn-sm" onclick="openEdit(${u.id},'${esc(u.username)}','${u.subscription}','${u.subscription_expires||''}','${u.is_elite}','${u.is_active}')">编辑</button>
        <button class="btn-sm" onclick="openPwd(${u.id},'${esc(u.username)}')">密码</button>
        <button class="btn-sm danger" onclick="delUser(${u.id},'${esc(u.username)}')">删除</button>
      </td>
    </tr>`).join('');
  document.getElementById('userCount').textContent = `共 ${data.length} 个用户`;
}

function esc(s) { return (s||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;'); }

function filterTable() {
  const q = document.getElementById('searchBox').value.toLowerCase();
  document.querySelectorAll('#userTable tr').forEach(tr => {
    tr.style.display = q ? (tr.dataset.search.toLowerCase().includes(q) ? '' : 'none') : '';
  });
}

function openEdit(id, name, sub, expires, elite, active) {
  document.getElementById('editUserId').value = id;
  document.getElementById('editUsername').textContent = name;
  document.getElementById('editSubscription').value = sub;
  document.getElementById('editExpires').value = (expires||'').slice(0,10);
  document.getElementById('editElite').value = elite==='True'||elite===true?'1':'0';
  document.getElementById('editActive').value = active==='True'||active===true?'1':'0';
  document.getElementById('editModal').classList.add('show');
}
function closeEdit() { document.getElementById('editModal').classList.remove('show'); }

async function saveUser() {
  const id = document.getElementById('editUserId').value;
  const body = {
    subscription: document.getElementById('editSubscription').value,
    is_elite: document.getElementById('editElite').value === '1',
    is_active: document.getElementById('editActive').value === '1',
    subscription_expires: document.getElementById('editExpires').value,
  };
  const r = await api('PUT', '/users/' + id, body);
  if (r) { closeEdit(); loadUsers(); toast('已保存'); }
}

function openPwd(id, name) {
  document.getElementById('pwdUserId').value = id;
  document.getElementById('pwdUsername').textContent = name;
  document.getElementById('newPassword').value = '';
  document.getElementById('pwdModal').classList.add('show');
}
function closePwd() { document.getElementById('pwdModal').classList.remove('show'); }

async function resetPwd() {
  const id = document.getElementById('pwdUserId').value;
  const pw = document.getElementById('newPassword').value;
  if (pw.length < 6) { toast('密码至少6位'); return; }
  const r = await api('PUT', '/users/' + id + '/password', { new_password: pw });
  if (r) { closePwd(); toast('密码已重置'); }
}

async function delUser(id, name) {
  if (!confirm('确认删除用户 "' + name + '"？此操作不可撤销。')) return;
  const r = await api('DELETE', '/users/' + id);
  if (r) { loadUsers(); toast('已删除'); }
}

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2000);
}
</script>
</body>
</html>"""


# ============================================================
# 反向代理核心函数 (使用 urllib，兼容 Python http.server 后端)
# ============================================================
def _do_proxy_sync(target_url: str, method: str, headers: dict, body: bytes) -> tuple:
    """
    同步执行 HTTP 代理请求。
    使用 urllib.request 而非 httpx，因为 Python http.server
    对 httpx 的某些 HTTP/1.1 特性存在兼容性问题。

    返回: (status_code, headers_dict, content_bytes)
    """
    req = urllib.request.Request(target_url, data=body if body else None, method=method)

    # 设置请求头
    for k, v in headers.items():
        if k.lower() not in ("host", "connection", "transfer-encoding"):
            try:
                req.add_header(k, v)
            except Exception:
                pass

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            resp_headers = dict(resp.headers)
            content = resp.read()
            return resp.status, resp_headers, content
    except urllib.error.HTTPError as e:
        # 后端返回了错误状态码，仍然需要转发
        resp_headers = dict(e.headers) if hasattr(e, 'headers') else {}
        content = e.read() if hasattr(e, 'read') else b""
        return e.code, resp_headers, content


async def _proxy(request: Request, strip_prefix: str = "") -> Response:
    """
    将请求透明转发到后端数学竞赛服务器 (127.0.0.1:8088)

    参数:
        strip_prefix: 从请求路径中剥离的前缀 (如 "/math")
                      例如 /math/xxx -> 后端收到 /xxx
    """
    # 路径重写：剥离前缀后转发给后端
    request_path = request.url.path
    if strip_prefix and request_path.startswith(strip_prefix):
        request_path = request_path[len(strip_prefix):]
        if not request_path.startswith("/"):
            request_path = "/" + request_path

    target_url = f"{BACKEND_URL}{request_path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # 准备转发头
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "connection", "transfer-encoding")
    }
    headers["X-Forwarded-For"] = request.client.host if request.client else "unknown"
    headers["X-Forwarded-Proto"] = request.url.scheme
    headers["X-Forwarded-Host"] = request.headers.get("host", "")

    # 读取请求体
    body = await request.body()

    path_display = request.url.path
    if request.url.query:
        path_display += f"?{request.url.query}"
    rewritten = f" -> {request_path}" if strip_prefix else ""
    logger.info(f"代理 {request.method} {path_display}{rewritten}")

    try:
        # 在线程池中运行同步 urllib 请求
        status_code, resp_headers, content = await asyncio.to_thread(
            _do_proxy_sync,
            target_url,
            request.method,
            headers,
            body,
        )

        # 过滤 hop-by-hop 响应头
        filtered_headers = {
            k: v for k, v in resp_headers.items()
            if k.lower() not in (
                "transfer-encoding", "connection", "keep-alive",
                "proxy-authenticate", "proxy-authorization", "te", "trailer",
                "date", "server",
            )
        }

        return Response(
            content=content,
            status_code=status_code,
            headers=filtered_headers,
        )

    except urllib.error.URLError as e:
        logger.error(f"连接后端失败 (8088端口未启动): {e.reason}")
        return HTMLResponse(
            content=get_error_page(
                "数学竞赛真题库 — 服务暂不可用",
                f"数学竞赛真题库服务暂未启动。请联系管理员或稍后重试。"
            ),
            status_code=502,
        )

    except Exception as e:
        logger.error(f"代理异常: {e}", exc_info=True)
        return HTMLResponse(
            content=get_error_page("代理请求失败", str(e)[:200]),
            status_code=500,
        )


# ============================================================
# API v1 路由 — 学习资源系统 + 用户认证系统（必须在 /api/* 代理之前注册）
# ============================================================
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(ai_router)
app.include_router(admin_router)
app.include_router(elite_router)
app.include_router(categories_router)
app.include_router(resources_router)
app.include_router(tags_router)
logger.info("API v1 路由已注册: /api/v1/auth, /api/v1/users, /api/v1/categories, /api/v1/resources, /api/v1/tags")
logger.info("速率限制已启用: 认证 10次/分钟 | AI 20次/分钟 | 上传 5次/分钟")


# ============================================================
# 数学竞赛真题库 — 内置在线阅读器（本地与线上共用同一套页面）
# ============================================================
#   文件来源（按优先级）:
#     1. 本地目录 static/uploads/10/（本机运行时直接读取）
#     2. CYJY_MATH_FILES_URL 指向的公网存储（如 Cloudflare R2 的 r2.dev 地址），
#        由本服务流式转发（支持 Range），浏览器始终同源访问，无需配置 CORS
#     3. 都没有时：仍可浏览目录，并提供 Google Drive 下载入口
#   本地若 8088 原版服务在运行，/math/ 默认继续代理过去（CYJY_MATH_PROXY=off 可关闭，
#   或访问 /math/?viewer=builtin 临时使用内置阅读器）。

from fastapi import HTTPException
from fastapi.responses import FileResponse as FileResp, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from urllib.parse import quote
import httpx
import mimetypes as _mimetypes

MATH_DIR = STATIC_DIR / "uploads" / "10"
_IS_RENDER = bool(os.environ.get("RENDER"))
MATH_FILES_URL = os.environ.get("CYJY_MATH_FILES_URL", "").strip().rstrip("/")
MATH_PROXY_MODE = os.environ.get("CYJY_MATH_PROXY", "auto").strip().lower()

# Google Drive 公开文件夹（文件未托管时的下载入口）
MATH_DRIVE_URL = os.environ.get(
    "CYJY_MATH_DRIVE_URL",
    "https://drive.google.com/drive/folders/1IiuEzpbNgePsdjCZxqXrZupT0q1TGAhX"
)

_MATH_HIDDEN = {".ds_store", "thumbs.db", "desktop.ini"}
_math_backend_cache = {"at": 0.0, "ok": False}
_math_catalog_cache = {"at": 0.0, "data": None}
_math_http = None


def _math_backend_available() -> bool:
    """快速检测 8088 原版数学竞赛服务是否在运行（结果缓存 5 秒）。"""
    now = _time.time()
    if now - _math_backend_cache["at"] < 5:
        return _math_backend_cache["ok"]
    try:
        urllib.request.urlopen(urllib.request.Request(f"{BACKEND_URL}/"), timeout=1.5)
        ok = True
    except Exception:
        ok = False
    _math_backend_cache.update(at=now, ok=ok)
    return ok


async def _use_math_legacy_proxy(request: Request) -> bool:
    if _IS_RENDER or MATH_PROXY_MODE in ("0", "off", "false", "no", "builtin"):
        return False
    if request.query_params.get("viewer") == "builtin":
        return False
    return await asyncio.to_thread(_math_backend_available)


def _math_visible(name: str) -> bool:
    return not name.startswith(".") and name.lower() not in _MATH_HIDDEN


def _clean_math_path(path: str):
    """规范化相对路径，拒绝 .. / 绝对路径等越界写法。"""
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts) or not _math_visible(parts[-1]):
        return None
    return "/".join(parts)


def _math_catalog() -> dict:
    now = _time.time()
    cached = _math_catalog_cache["data"]
    if cached and now - _math_catalog_cache["at"] < 60:
        return cached

    years = []
    if MATH_DIR.exists():
        mode = "local"
        for d in sorted((p for p in MATH_DIR.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
            files = []
            for f in sorted(d.rglob("*")):
                if f.is_file() and _math_visible(f.name):
                    files.append({"p": f.relative_to(MATH_DIR).as_posix(), "s": f.stat().st_size})
            years.append({"name": d.name, "files": files})
    else:
        mode = "remote" if MATH_FILES_URL else "offline"
        catalog_path = BASE_DIR / "math_catalog.json"
        if catalog_path.exists():
            for y in _json.loads(catalog_path.read_text(encoding="utf-8")):
                sizes = y.get("sizes") or {}
                files = [
                    {"p": p, "s": sizes.get(p)}
                    for p in list(y.get("pdfs", [])) + list(y.get("others", []))
                    if _math_visible(p.rsplit("/", 1)[-1])
                ]
                years.append({"name": y["name"], "files": files})

    all_files = [f for y in years for f in y["files"]]
    data = {
        "mode": mode,
        "files_base": "/math/files/",
        "drive_url": MATH_DRIVE_URL,
        "years": years,
        "total": len(all_files),
        "pdfs": sum(1 for f in all_files if f["p"].lower().endswith(".pdf")),
    }
    _math_catalog_cache.update(at=now, data=data)
    return data


@app.get("/api/v1/math/catalog", include_in_schema=False)
async def math_catalog_api():
    return JSONResponse(_math_catalog(), headers={"Cache-Control": "public, max-age=300"})


async def _math_client() -> httpx.AsyncClient:
    global _math_http
    if _math_http is None:
        _math_http = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, read=120.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=8),
        )
    return _math_http


def _content_disposition(name: str, download: bool) -> str:
    return f"{'attachment' if download else 'inline'}; filename*=UTF-8''{quote(name)}"


async def _stream_math_remote(rel: str, request: Request, download: bool) -> Response:
    """从公网存储流式转发文件，透传 Range，保证 PDF.js 可分段加载。"""
    url = f"{MATH_FILES_URL}/{quote(rel)}"
    fwd = {}
    for h in ("range", "if-range", "if-none-match", "if-modified-since"):
        if h in request.headers:
            fwd[h] = request.headers[h]
    client = await _math_client()
    try:
        upstream = await client.send(client.build_request("GET", url, headers=fwd), stream=True)
    except httpx.HTTPError as e:
        logger.warning(f"真题文件存储连接失败: {rel} ({e.__class__.__name__})")
        return JSONResponse({"detail": "文件存储暂时无法访问，请稍后重试"}, status_code=502)
    if upstream.status_code not in (200, 206, 304, 416):
        await upstream.aclose()
        code = 404 if upstream.status_code in (403, 404) else 502
        return JSONResponse({"detail": "文件不存在或暂不可访问"}, status_code=code)

    headers = {
        k: upstream.headers[k]
        for k in ("content-length", "content-range", "accept-ranges", "etag", "last-modified", "content-encoding")
        if k in upstream.headers
    }
    headers.setdefault("accept-ranges", "bytes")
    ctype = upstream.headers.get("content-type", "")
    guessed = _mimetypes.guess_type(rel)[0]
    if guessed and (not ctype or "octet-stream" in ctype):
        ctype = guessed
    headers["content-type"] = ctype or "application/octet-stream"
    headers["content-disposition"] = _content_disposition(rel.rsplit("/", 1)[-1], download)
    headers["cache-control"] = "public, max-age=86400"
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=headers,
        background=BackgroundTask(upstream.aclose),
    )


@app.get("/math/files/{path:path}", include_in_schema=False)
async def math_file(path: str, request: Request):
    """真题文件：本地目录直读，否则从公网存储转发；?download=1 触发下载。"""
    rel = _clean_math_path(path)
    if rel is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    download = request.query_params.get("download") == "1"
    name = rel.rsplit("/", 1)[-1]

    if MATH_DIR.exists():
        base = MATH_DIR.resolve()
        fp = (MATH_DIR / rel).resolve()
        if base in fp.parents and fp.is_file():
            return FileResp(
                fp,
                filename=name,
                content_disposition_type="attachment" if download else "inline",
                headers={"Cache-Control": "public, max-age=86400"},
            )
    if MATH_FILES_URL:
        # 大体积压缩包直接跳转到存储地址下载，节省本服务带宽
        if download and not name.lower().endswith(".pdf"):
            return RedirectResponse(url=f"{MATH_FILES_URL}/{quote(rel)}", status_code=302)
        return await _stream_math_remote(rel, request, download)
    raise HTTPException(status_code=404, detail="文件暂未上线，请通过 Google Drive 下载")


@app.get("/math", include_in_schema=False)
@app.get("/math/", include_in_schema=False)
async def math_index(request: Request):
    """数学竞赛真题库首页：内置阅读器（本地 8088 在线时默认沿用原版站点）"""
    if await _use_math_legacy_proxy(request):
        return await _proxy(request, strip_prefix="/math")
    page = STATIC_DIR / "math.html"
    if not page.exists():
        return HTMLResponse(content=get_error_page("页面未找到", "math.html"), status_code=200)
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/math/{path:path}", include_in_schema=False)
async def serve_or_proxy_math(request: Request, path: str):
    """旧链接兼容：本地 8088 在线则代理；否则跳到阅读器中对应文件。"""
    if await _use_math_legacy_proxy(request):
        return await _proxy(request, strip_prefix="/math")
    rel = _clean_math_path(path)
    if rel is None:
        return RedirectResponse(url="/math/")
    return RedirectResponse(url=f"/math/#/{quote(rel)}")


@app.get("/pdf", include_in_schema=False)
@app.get("/pdf/{path:path}", include_in_schema=False)
async def pdf_proxy_or_redirect(request: Request, path: str = ""):
    """旧 /pdf/ 路径：本地 8088 在线则代理，否则进入阅读器"""
    if await _use_math_legacy_proxy(request):
        return await _proxy(request)
    rel = _clean_math_path(path) if path else None
    return RedirectResponse(url=f"/math/#/{quote(rel)}" if rel else "/math/")


# ============================================================
# 全局异常处理 - 不暴露 Python Traceback
# ============================================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    logger.warning(f"404: {request.method} {request.url.path}")
    return HTMLResponse(
        content=get_error_page("404 - 页面未找到", "您访问的页面不存在。"),
        status_code=404,
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.error(f"500: {request.method} {request.url.path}")
    return HTMLResponse(
        content=get_error_page("500 - 服务器内部错误", "请稍后重试。"),
        status_code=500,
    )


@app.exception_handler(429)
async def rate_limit_handler(request: Request, exc):
    logger.warning(f"429 Rate limit: {request.client.host if request.client else '?'} -> {request.url.path}")
    return HTMLResponse(
        content=get_error_page("429 - Too Many Requests", "Please retry later."),
        status_code=429,
        headers={"Retry-After": "60"},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常兜底 - 捕获所有未处理异常"""
    logger.error(
        f"未处理异常: {request.method} {request.url.path} - {exc}",
        exc_info=True,
    )
    return HTMLResponse(
        content=get_error_page("发生了一些错误", "请稍后重试，或联系管理员。"),
        status_code=500,
    )


# ============================================================
# 健康检查接口
# ============================================================

@app.get("/organic.html")
async def redirect_organic():
    return RedirectResponse(url="/chemistry/organic.html")

@app.get("/chemistry", response_class=HTMLResponse)
async def serve_chemistry_index():
    path = STATIC_DIR / "chemistry" / "index.html"
    if not path.exists():
        return HTMLResponse(content=get_error_page("页面未找到", "chemistry/index.html"), status_code=200)
    return HTMLResponse(path.read_text(encoding="utf-8"))

@app.get("/chemistry/{page}", response_class=HTMLResponse)
async def serve_chemistry_page(page: str):
    file_path = STATIC_DIR / "chemistry" / page
    if not file_path.exists() or not file_path.suffix == ".html":
        return HTMLResponse(content=get_error_page("页面未找到", f"chemistry/{page}"), status_code=200)
    return HTMLResponse(file_path.read_text(encoding="utf-8"))


@app.get("/robots.txt", include_in_schema=False)
async def robots():
    return Response(
        content="User-agent: *\nAllow: /\nSitemap: https://chongyue-jianyuan.onrender.com/sitemap.xml\n",
        media_type="text/plain",
    )


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    urls = [
        ("/", "daily", "1.0"),
        ("/knowledge", "daily", "0.9"),
        ("/knowledge-base", "weekly", "0.8"),
        ("/ai-coding", "weekly", "0.8"),
        ("/research", "weekly", "0.7"),
        ("/math", "weekly", "0.9"),
        ("/math-hub", "weekly", "0.85"),
        ("/signals-and-systems", "weekly", "0.85"),
        ("/chemistry", "weekly", "0.7"),
        ("/python-course", "monthly", "0.6"),
        ("/pricing", "monthly", "0.5"),
        ("/login", "monthly", "0.3"),
    ]
    items = "\n".join(
        f"  <url><loc>https://chongyue-jianyuan.onrender.com{u}</loc><changefreq>{freq}</changefreq><priority>{pri}</priority></url>"
        for u, freq, pri in urls
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{items}\n</urlset>'
    return Response(content=xml, media_type="application/xml")


@app.get("/health", include_in_schema=False)
async def health_check():
    return {
        "status": "ok",
        "backend": BACKEND_URL,
        "cors_origins": [o.strip() for o in CORS_ORIGINS if o.strip()],
        "rate_limiting": "enabled",
        "timestamp": datetime.now().isoformat(),
    }


# ============================================================
# 启动入口
# ============================================================
def main():
    """启动统一入口服务器"""
    port = int(os.environ.get("PORT", 8888))
    print()
    print("=" * 55)
    print("  崇岳鉴渊 - 统一入口服务器 (FastAPI)")
    print("=" * 55)
    print(f"  静态文件: {STATIC_DIR}")
    print(f"  日志目录: {LOGS_DIR}")
    print(f"  后端代理: {BACKEND_URL}")
    print(f"  监听地址: http://0.0.0.0:{port}")
    print(f"  本机访问: http://127.0.0.1:{port}")
    print("=" * 55)
    print()

    uvicorn.run(
        "unified_server:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()