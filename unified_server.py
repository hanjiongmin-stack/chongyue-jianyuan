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
import sys
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
import urllib.request
import urllib.error

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
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
    "http://localhost:8888,http://127.0.0.1:8888,http://localhost:3000,http://localhost:5173"
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


@app.get("/python-course", response_class=HTMLResponse)
async def serve_python_course():
    """返回Python数据分析课程页（像素AI风格）"""
    path = STATIC_DIR / "python-course.html"
    if not path.exists():
        return HTMLResponse(content=get_error_page("页面未找到", "python-course.html"), status_code=200)
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
app.include_router(categories_router)
app.include_router(resources_router)
app.include_router(tags_router)
logger.info("API v1 路由已注册: /api/v1/auth, /api/v1/users, /api/v1/categories, /api/v1/resources, /api/v1/tags")
logger.info("速率限制已启用: 认证 10次/分钟 | AI 20次/分钟 | 上传 5次/分钟")


# ============================================================
# 数学竞赛真题库 — 直接从 uploads/10/ 服务文件（无需本地 8088）
# ============================================================

from fastapi.responses import FileResponse as FileResp

MATH_DIR = STATIC_DIR / "uploads" / "10"

# Cloudflare R2 公网访问地址（配置后自动启用远程下载）
R2_PUBLIC_URL = os.environ.get("CYJY_R2_PUBLIC_URL", "").rstrip("/")


def _math_file_url(rel_path: str) -> str:
    """返回数学竞赛文件的访问链接。有 R2 则用 R2，否则走本地 /math/ 路径。"""
    if R2_PUBLIC_URL:
        return f"{R2_PUBLIC_URL}/{rel_path}"
    return f"/math/{rel_path}"


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    else:
        return f"{size / (1024 * 1024):.1f}MB"


@app.get("/math", include_in_schema=False, response_class=HTMLResponse)
@app.get("/math/", include_in_schema=False, response_class=HTMLResponse)
async def math_index():
    """动态生成数学竞赛真题库目录页"""
    if not MATH_DIR.exists():
        return HTMLResponse(content=get_error_page(
            "数学竞赛真题库 — 服务暂不可用",
            "真题库文件尚未上传到云端，请联系管理员。"
        ), status_code=200)

    # 收集所有年份目录
    years = []
    for d in sorted(MATH_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        pdfs = []
        others = []
        for f in sorted(d.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(MATH_DIR).as_posix()
            if f.suffix.lower() == ".pdf":
                pdfs.append(rel)
            else:
                others.append(rel)

        years.append({
            "name": d.name,
            "pdfs": pdfs,
            "others": others,
            "total": len(pdfs) + len(others),
        })

    total_pdfs = sum(len(y["pdfs"]) for y in years)
    total_files = sum(y["total"] for y in years)

    # 生成 HTML
    year_items = []
    for y in years:
        items = ""
        for p in y["pdfs"]:
            fname = p.split("/")[-1]
            items += f'<li class="pdf"><a href="{_math_file_url(p)}" target="_blank">📄 {fname}</a></li>\n'
        for o in y["others"]:
            fname = o.split("/")[-1]
            ext = fname.rsplit(".", 1)[-1] if "." in fname else ""
            icon = {"zip": "📦", "rar": "📦", "7z": "📦", "pptx": "📊", "docx": "📝", "xlsx": "📊", "csv": "📊"}.get(ext, "📎")
            items += f'<li class="other"><a href="{_math_file_url(o)}">🖱 {fname}</a></li>\n'

        year_items.append(f'''
        <details class="year-group">
          <summary><strong>{y["name"]}</strong> <span class="count">({y["total"]} 个文件)</span></summary>
          <ul class="file-list">{items}</ul>
        </details>''')

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>数学竞赛真题库 — 崇岳鉴渊</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{
    font-family:"Instrument Sans","Microsoft YaHei",system-ui,sans-serif;
    background:#fbfbfa;color:#1a1a18;line-height:1.6;
    max-width:960px;margin:0 auto;padding:2rem 1.5rem;
  }}
  [data-theme="dark"] body{{background:#111110;color:#f0f0ee}}
  h1{{font-size:1.5rem;font-weight:500;margin-bottom:.25rem;letter-spacing:-.01em}}
  .subtitle{{color:#6b6b66;font-size:.875rem;margin-bottom:2rem}}
  .stats{{display:flex;gap:2rem;margin-bottom:2rem;font-size:.875rem;color:#6b6b66}}
  .year-group{{margin-bottom:.75rem;border:1px solid rgba(26,26,24,.08);border-radius:6px;padding:.75rem 1rem;background:#fff}}
  [data-theme="dark"] .year-group{{background:#1a1a18;border-color:rgba(240,240,238,.1)}}
  .year-group summary{{cursor:pointer;font-size:.9375rem;user-select:none}}
  .year-group summary:hover{{opacity:.7}}
  .count{{font-weight:400;color:#6b6b66;font-size:.8125rem;margin-left:.5rem}}
  .file-list{{list-style:none;margin-top:.5rem;padding-left:0;max-height:500px;overflow-y:auto}}
  .file-list li{{padding:2px 0;font-size:.8125rem}}
  .file-list a{{color:#1a1a18;text-decoration:none}}
  .file-list a:hover{{text-decoration:underline}}
  .back-link{{display:inline-block;margin-top:2rem;font-size:.8125rem;color:#6b6b66;text-decoration:none}}
  .back-link:hover{{color:#1a1a18}}
</style>
</head>
<body>
<h1>🎓 数学竞赛真题库</h1>
<p class="subtitle">全国大学生数学竞赛（CMC）/ 美赛（MCM/ICM）历年真题与特等奖论文</p>
<div class="stats">
  <span>📁 {len(years)} 个年份</span>
  <span>📄 {total_pdfs} 篇 PDF</span>
  <span>📦 {total_files} 个文件</span>
</div>
{"".join(year_items)}
<a href="/" class="back-link">&larr; 返回首页</a>
</body>
</html>'''
    return HTMLResponse(content=html)


@app.get("/math/{path:path}", include_in_schema=False)
async def serve_math_file(path: str):
    """直接服务数学竞赛文件（PDF / ZIP / RAR 等）；目录重定向回列表页"""
    file_path = MATH_DIR / path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    if file_path.is_dir():
        # 目录 → 重定向回主页，浏览器会自动定位到该年份
        return RedirectResponse(url=f"/math/#{file_path.name}")
    return FileResp(file_path)


# /pdf -> 重定向到 /math/
@app.get("/pdf", include_in_schema=False)
@app.get("/pdf/{path:path}", include_in_schema=False)
async def redirect_pdf(path: str = ""):
    """旧 /pdf/ 路径重定向到 /math/"""
    target = "/math/" + path if path else "/math/"
    return RedirectResponse(url=target)


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