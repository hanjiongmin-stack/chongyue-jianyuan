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
from html import escape as html_escape
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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
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
logging.getLogger("httpx").setLevel(logging.WARNING)


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
    # 顶层共享样式/脚本（cyjy.*、chem.* 等）任一变化都会刷新版本号
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
    p = STATIC_DIR / "admin.html"
    if not p.exists(): return HTMLResponse(content=get_error_page("页面未找到", "admin.html"), status_code=200)
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
    """管理后台（用户管理 + 精英审批，仅管理员可用，权限由 API 校验）"""
    p = STATIC_DIR / "admin.html"
    if not p.exists(): return HTMLResponse(content=get_error_page("页面未找到", "admin.html"), status_code=200)
    return HTMLResponse(p.read_text(encoding="utf-8"))


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
    """生成统一风格的错误页面 HTML（沿用全站导航/页脚；title、detail 一律转义）"""
    m = re.match(r"^\s*(\d{3})\s*[-–—:]?\s*(.*)$", title or "")
    code, heading = (m.group(1), m.group(2) or title) if m else ("", title or "出错了")
    if not code:
        code = "404" if "未找到" in heading else "Oops"
    code_e, heading_e, detail_e = (html_escape(x) for x in (code, heading, detail or ""))
    page = f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{heading_e} | 崇岳鉴渊</title>
<meta name="robots" content="noindex">
<!--cy:head-->
<style>
.err{{position:relative;min-height:100vh;display:grid;place-items:center;padding:calc(var(--nav-h) + 40px) 20px 72px;text-align:center;overflow:hidden;isolation:isolate}}
.err .ph-bg{{position:absolute}}
.err-code{{font-family:var(--font-brush);font-size:clamp(6rem,22vw,12rem);line-height:1;letter-spacing:.02em;background:var(--grad);background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent;animation:cy-shimmer 6s linear infinite,err-float 5s ease-in-out infinite}}
@keyframes err-float{{50%{{transform:translateY(-10px)}}}}
.err h1{{margin-top:6px;font-size:clamp(1.5rem,3vw,2.1rem);font-weight:800;letter-spacing:-.02em}}
.err p{{margin:12px auto 0;max-width:520px;color:var(--muted);line-height:1.8;word-break:break-word}}
.err .ph-actions{{justify-content:center}}
.err .chips{{justify-content:center;margin-top:26px}}
@media(prefers-reduced-motion:reduce){{.err-code{{animation:none}}}}
</style>
</head>
<body>
<!--cy:nav-->
<main class="err">
  <div class="ph-bg" aria-hidden="true"><i></i><i></i></div>
  <div>
    <div class="err-code" aria-hidden="true">{code_e}</div>
    <h1>{heading_e}</h1>
    <p>{detail_e}</p>
    <div class="ph-actions">
      <a class="btn btn-primary btn-lg" href="/">返回首页</a>
      <a class="btn btn-ghost btn-lg" href="javascript:history.back()">返回上一页</a>
    </div>
    <div class="chips" aria-label="常用入口">
      <a class="chip" href="/math">数学竞赛真题库</a><a class="chip" href="/knowledge">知识库</a><a class="chip" href="/ai-coding">AI 编程</a><a class="chip" href="/chemistry">高等化学</a><a class="chip" href="/pricing">平台通道</a>
    </div>
  </div>
</main>
<!--cy:footer-->
<!--cy:tail-lite-->
</body>
</html>"""
    return _apply_partials(page)


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
#     3. CYJY_GDRIVE_API_KEY：直接读取公开的 Google Drive 文件夹（文件无需另行上传），
#        目录按文件夹结构自动生成，文件经 Drive API 同源转发（支持 Range）
#     4. 都没有时：仍可浏览目录（math_catalog.json），并提供 Google Drive 下载入口
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
# 配置 Google API Key 后直接从上面的文件夹在线阅读（文件夹需设为“知道链接的任何人可查看”）
GDRIVE_API_KEY = os.environ.get("CYJY_GDRIVE_API_KEY", "").strip()
GDRIVE_API = os.environ.get("CYJY_GDRIVE_API_BASE", "https://www.googleapis.com/drive/v3").strip().rstrip("/")
_drive_folder_match = re.search(r"/folders/([\w-]+)", MATH_DRIVE_URL)
GDRIVE_FOLDER = os.environ.get("CYJY_MATH_DRIVE_FOLDER", "").strip() or (
    _drive_folder_match.group(1) if _drive_folder_match else ""
)
if GDRIVE_API_KEY and not GDRIVE_FOLDER:
    logger.warning("已设置 CYJY_GDRIVE_API_KEY，但 CYJY_MATH_DRIVE_URL 不是文件夹链接，Drive 在线阅读未启用")

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

    data = _math_payload(mode, years)
    _math_catalog_cache.update(at=now, data=data)
    return data


def _math_payload(mode: str, years: list) -> dict:
    all_files = [f for y in years for f in y["files"]]
    return {
        "mode": mode,
        "files_base": "/math/files/",
        "drive_url": MATH_DRIVE_URL,
        "years": years,
        "total": len(all_files),
        "pdfs": sum(1 for f in all_files if f["p"].lower().endswith(".pdf")),
    }


# ---- Google Drive 直读 ----------------------------------------------------
_GD_FOLDER = "application/vnd.google-apps.folder"
_GD_SHORTCUT = "application/vnd.google-apps.shortcut"
_GD_NATIVE = "application/vnd.google-apps."
_DRIVE_TTL = 1800          # 目录缓存 30 分钟，过期后后台刷新
_DRIVE_RETRY = 60          # 读取失败后至少间隔 60 秒再试
_drive_cache = {"at": 0.0, "failed_at": 0.0, "data": None, "index": {}, "task": None}
_drive_lock = asyncio.Lock()


class _DriveError(Exception):
    pass


def _math_drive_enabled() -> bool:
    return bool(GDRIVE_API_KEY and GDRIVE_FOLDER) and not MATH_FILES_URL and not MATH_DIR.exists()


def _drive_headers() -> dict:
    # Key 放在请求头而不是 URL 里，避免出现在任何请求日志中
    return {"x-goog-api-key": GDRIVE_API_KEY, "accept-encoding": "identity"}


def _drive_reason(body: bytes) -> str:
    """从 Drive API 的错误 JSON 中取出 reason（日志用，绝不包含 Key）。"""
    try:
        err = _json.loads(body or b"{}").get("error") or {}
        return ((err.get("errors") or [{}])[0].get("reason") or err.get("status") or "")[:80]
    except Exception:
        return ""


async def _drive_list(client: httpx.AsyncClient, folder_id: str) -> list:
    items, token = [], None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,size,shortcutDetails(targetId,targetMimeType))",
            "pageSize": "1000",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if token:
            params["pageToken"] = token
        r = await client.get(f"{GDRIVE_API}/files", params=params, headers=_drive_headers())
        if r.status_code != 200:
            raise _DriveError(f"HTTP {r.status_code} {_drive_reason(r.content)}")
        d = r.json()
        items.extend(d.get("files") or [])
        token = d.get("nextPageToken")
        if not token:
            return items


def _drive_target(item: dict):
    """返回 (mimeType, id)，快捷方式解析为其指向的文件或文件夹。"""
    if item.get("mimeType") == _GD_SHORTCUT:
        sd = item.get("shortcutDetails") or {}
        return sd.get("targetMimeType", ""), sd.get("targetId")
    return item.get("mimeType", ""), item.get("id")


async def _drive_scan():
    """遍历公开文件夹：第一层子文件夹作为“年份”，其下（含子目录）的文件进入目录。"""
    client = await _math_client()
    sem = asyncio.Semaphore(8)

    async def ls(fid):
        async with sem:
            return await _drive_list(client, fid)

    def name_of(item):
        return (item.get("name") or "").strip().replace("/", "／").replace("\\", "＼")

    root = GDRIVE_FOLDER
    top = await ls(root)
    for _ in range(3):  # 共享文件夹外面只包了一层文件夹时自动进入
        visible = [k for k in top if name_of(k) and _math_visible(name_of(k))]
        if len(visible) == 1 and _drive_target(visible[0])[0] == _GD_FOLDER and not name_of(visible[0]).isdigit():
            root = _drive_target(visible[0])[1]
            top = await ls(root)
        else:
            break

    index, sizes, seen = {}, {}, {root}
    level = [("", top)]
    while level:
        subfolders = []
        for prefix, kids in level:
            for k in kids:
                name = name_of(k)
                mime, fid = _drive_target(k)
                if not name or not fid or not _math_visible(name):
                    continue
                rel = prefix + name
                if mime == _GD_FOLDER:
                    if fid not in seen:
                        seen.add(fid)
                        subfolders.append((fid, rel + "/"))
                elif prefix and not mime.startswith(_GD_NATIVE) and rel not in index:
                    index[rel] = fid
                    size = str(k.get("size") or "")
                    sizes[rel] = int(size) if size.isdigit() else None
        results = await asyncio.gather(*(ls(fid) for fid, _ in subfolders))
        level = [(prefix, kids) for (_, prefix), kids in zip(subfolders, results)]

    groups = {}
    for rel in sorted(index):
        groups.setdefault(rel.split("/", 1)[0], []).append({"p": rel, "s": sizes[rel]})
    order = sorted(groups, key=lambda n: (0, -int(n)) if n.isdigit() else (1, n))
    return [{"name": n, "files": groups[n]} for n in order], index


async def _drive_refresh():
    try:
        years, index = await _drive_scan()
        if not index:
            raise _DriveError("文件夹为空或未公开共享")
    except Exception as e:
        _drive_cache["failed_at"] = _time.time()
        detail = str(e) if isinstance(e, _DriveError) else ""
        logger.warning(f"Google Drive 真题目录读取失败: {e.__class__.__name__} {detail}")
        return
    _drive_cache.update(at=_time.time(), data=_math_payload("drive", years), index=index)
    logger.info(f"Google Drive 真题目录已更新: {len(index)} 个文件")


async def _drive_refresh_locked(max_age: float = _DRIVE_TTL):
    async with _drive_lock:
        c, now = _drive_cache, _time.time()
        if now - c["failed_at"] < _DRIVE_RETRY:
            return
        if c["data"] is None or now - c["at"] >= max_age:
            await _drive_refresh()


def _drive_refresh_bg():
    task = _drive_cache["task"]
    if task is None or task.done():
        _drive_cache["task"] = asyncio.create_task(_drive_refresh_locked())


async def _drive_catalog():
    """Drive 目录：有缓存直接返回（过期则后台刷新），首次读取时等待结果；失败返回 None。"""
    c = _drive_cache
    if c["data"] is None:
        await _drive_refresh_locked()
    elif _time.time() - c["at"] >= _DRIVE_TTL:
        _drive_refresh_bg()
    return c["data"]


async def _drive_file_id(rel: str):
    if await _drive_catalog() is None:
        return None
    fid = _drive_cache["index"].get(rel)
    if fid is None and _time.time() - _drive_cache["at"] > _DRIVE_RETRY:
        # 可能是刚上传到 Drive 的新文件：最多每分钟强制刷新一次目录
        await _drive_refresh_locked(max_age=_DRIVE_RETRY)
        fid = _drive_cache["index"].get(rel)
    return fid


@app.get("/api/v1/math/catalog", include_in_schema=False)
async def math_catalog_api():
    if _math_drive_enabled():
        data = await _drive_catalog()
        if data is not None:
            return JSONResponse(data, headers={"Cache-Control": "public, max-age=300"})
        # Drive 暂不可用：退回目录浏览，短缓存以便尽快恢复
        return JSONResponse(_math_catalog(), headers={"Cache-Control": "public, max-age=60"})
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


async def _stream_math_remote(url: str, rel: str, request: Request, download: bool, drive: bool = False) -> Response:
    """从公网存储或 Google Drive 流式转发文件，透传 Range，保证 PDF.js 可分段加载。"""
    fwd = _drive_headers() if drive else {}
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
        body = b""
        try:
            async for chunk in upstream.aiter_raw():
                body += chunk
                if len(body) > 4096:
                    break
        except httpx.HTTPError:
            pass
        finally:
            await upstream.aclose()
        reason = _drive_reason(body) if drive else ""
        logger.warning(f"真题文件读取失败: {rel} -> HTTP {upstream.status_code} {reason}")
        # Drive 的 403 多为下载次数/频率限制，而不是文件不存在
        if upstream.status_code == 404 or (upstream.status_code == 403 and not drive):
            return JSONResponse({"detail": "文件不存在或暂不可访问"}, status_code=404)
        return JSONResponse({"detail": "文件暂时无法读取，请稍后重试"}, status_code=502)

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
    """真题文件：本地目录直读，否则从公网存储或 Google Drive 转发；?download=1 触发下载。"""
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
        return await _stream_math_remote(f"{MATH_FILES_URL}/{quote(rel)}", rel, request, download)
    if _math_drive_enabled():
        fid = await _drive_file_id(rel)
        if fid is None:
            raise HTTPException(status_code=404, detail="文件不存在或暂不可访问")
        if request.query_params.get("drive") == "1":
            return RedirectResponse(url=f"https://drive.google.com/file/d/{quote(fid)}/view", status_code=302)
        if download and not name.lower().endswith(".pdf"):
            return RedirectResponse(url=f"https://drive.google.com/uc?export=download&id={quote(fid)}", status_code=302)
        url = f"{GDRIVE_API}/files/{quote(fid)}?alt=media&supportsAllDrives=true"
        return await _stream_math_remote(url, rel, request, download, drive=True)
    raise HTTPException(status_code=404, detail="文件暂未上线，请通过 Google Drive 下载")


@app.get("/math", include_in_schema=False)
@app.get("/math/", include_in_schema=False)
async def math_index(request: Request):
    """数学竞赛真题库首页：内置阅读器（本地 8088 在线时默认沿用原版站点）"""
    if await _use_math_legacy_proxy(request):
        return await _proxy(request, strip_prefix="/math")
    if _math_drive_enabled() and _drive_cache["data"] is None:
        _drive_refresh_bg()  # 提前读取 Drive 目录，页面脚本请求目录时通常已就绪
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

def _is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def _detail(exc, default: str):
    d = getattr(exc, "detail", None)
    return d if d else default


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    logger.warning(f"404: {request.method} {request.url.path}")
    if _is_api(request):
        # API 调用方需要 JSON 的 detail（例如“资源不存在”），不能被换成 HTML 页面
        return JSONResponse({"detail": _detail(exc, "Not Found")}, status_code=404)
    return HTMLResponse(
        content=get_error_page("404 - 页面未找到", "你访问的页面不存在，可能已被移动或删除。"),
        status_code=404,
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.error(f"500: {request.method} {request.url.path}")
    if _is_api(request):
        return JSONResponse({"detail": "服务器内部错误，请稍后重试"}, status_code=500)
    return HTMLResponse(
        content=get_error_page("500 - 服务器内部错误", "请稍后重试。"),
        status_code=500,
    )


@app.exception_handler(429)
async def rate_limit_handler(request: Request, exc):
    logger.warning(f"429 Rate limit: {request.client.host if request.client else '?'} -> {request.url.path}")
    if _is_api(request):
        return JSONResponse({"detail": "操作太频繁，请稍后再试"}, status_code=429, headers={"Retry-After": "60"})
    return HTMLResponse(
        content=get_error_page("429 - 请求过于频繁", "请稍等一分钟后再试。"),
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
    if _is_api(request):
        return JSONResponse({"detail": "服务器内部错误，请稍后重试"}, status_code=500)
    return HTMLResponse(
        content=get_error_page("500 - 发生了一些错误", "请稍后重试，或联系管理员。"),
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