"""Security utilities for ChongYue JianYuan - rate limiter, secure filenames, security headers."""

import ipaddress
import json
import os
import re
import time
import hashlib
import secrets
import threading
import unicodedata
from pathlib import Path
from typing import Optional
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


# ============================================================
# 1. Secure key generation - NEVER use the default in production
# ============================================================
_SECRET_FILE = Path(__file__).resolve().parent / '.secret_key'


def _secret_from_database() -> Optional[str]:
    """使用外部数据库时，把自动生成的密钥存进数据库：Render 的本地文件每次重启都会丢失，密钥一变，所有人都得重新登录。"""
    from database import IS_SQLITE, SessionLocal, engine
    if IS_SQLITE:
        return None
    from sqlalchemy.exc import IntegrityError
    from models import AppSetting
    AppSetting.__table__.create(bind=engine, checkfirst=True)
    with SessionLocal() as db:
        row = db.get(AppSetting, 'jwt_secret')
        if row:
            return row.value
        key = secrets.token_urlsafe(48)
        db.add(AppSetting(key='jwt_secret', value=key))
        try:
            db.commit()
        except IntegrityError:  # 另一个进程刚刚写入了密钥
            db.rollback()
            return db.get(AppSetting, 'jwt_secret').value
        return key


def get_secret_key() -> str:
    """登录令牌的签名密钥：环境变量 CYJY_SECRET_KEY 优先；否则保存在外部数据库或本地 .secret_key 文件中，重启后保持不变。"""
    key = os.environ.get('CYJY_SECRET_KEY')
    if key:
        return key
    key = _secret_from_database()
    if key:
        return key
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text().strip()
    # Generate and persist
    key = secrets.token_urlsafe(32)
    _SECRET_FILE.write_text(key)
    import logging
    logging.warning(
        'WARNING: SECRET_KEY auto-generated and saved to .secret_key. '
        'Set CYJY_SECRET_KEY env var for production!'
    )
    return key


# ============================================================
# 2. Rate limiter - in-memory sliding window
# ============================================================
_ON_RENDER = bool(os.environ.get("RENDER"))


def _valid_ip(value: str) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    """访客的真实 IP。

    Render 的请求先经过 Cloudflare 和 Render 自己的代理，socket 地址是代理的内网地址，所有访客都一样。
    Cloudflare 会用它实际收到的连接地址覆盖 CF-Connecting-IP，访客无法伪造；
    X-Forwarded-For 的第一项则是访客自己可以随便填的（Render 只在后面追加），不能用来限流。
    """
    if _ON_RENDER:
        ip = _valid_ip(request.headers.get("cf-connecting-ip", ""))
        if ip:
            return ip
        # 兜底：X-Forwarded-For 形如「<伪造的>, <访客>, <Cloudflare>, <Render 内网>」，取右数第三项
        hops = [h for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(hops) >= 3:
            ip = _valid_ip(hops[-3])
            if ip:
                return ip
    return request.client.host if request.client else "unknown"


def client_key(request: Request) -> str:
    """限流计数用的访客标识（IP 的哈希，内存里不保存原始 IP）。"""
    return hashlib.sha256(client_ip(request).encode()).hexdigest()[:16]


class RateLimiter:
    """Simple in-memory rate limiter: at most `max_requests` per `window_seconds` for each key (default: client IP)."""

    MAX_KEYS = 20_000   # 防止大量不同的 key 把内存撑大

    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients = {}
        self._lock = threading.Lock()

    def _get_client_key(self, request: Request) -> str:
        # 每个限流器只用于一类接口，按访客 IP 计数即可；不把路径放进 key，避免带参数的路径制造无数个 key
        return client_key(request)

    def hit(self, key: str) -> bool:
        """记一次访问；超过限额时返回 False。"""
        now = time.time()
        window_start = now - self.window_seconds
        with self._lock:
            timestamps = [t for t in self._clients.get(key, ()) if t > window_start]
            if len(timestamps) >= self.max_requests:
                self._clients[key] = timestamps
                return False
            timestamps.append(now)
            self._clients[key] = timestamps
            if len(self._clients) > self.MAX_KEYS:
                self._prune(window_start)
            return True

    def check(self, request: Request) -> bool:
        return self.hit(self._get_client_key(request))

    def count(self, key: str) -> int:
        window_start = time.time() - self.window_seconds
        with self._lock:
            return sum(1 for t in self._clients.get(key, ()) if t > window_start)

    def reset(self, key: str) -> None:
        with self._lock:
            self._clients.pop(key, None)

    def _prune(self, window_start: float) -> None:
        for key in [k for k, ts in self._clients.items() if not ts or ts[-1] <= window_start]:
            del self._clients[key]
        if len(self._clients) > self.MAX_KEYS:   # 仍然太多：丢掉最早的一半
            for key in list(self._clients)[: len(self._clients) // 2]:
                del self._clients[key]

    def cleanup(self):
        with self._lock:
            self._prune(time.time() - self.window_seconds)

    def limit(self, request: Request, key: Optional[str] = None):
        """超过限额时抛出 429。key 默认是访客 IP，也可以传入别的计数对象（如用户名）。"""
        if not self.hit(key or self._get_client_key(request)):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail='操作太频繁，请稍后再试',
                headers={'Retry-After': str(self.window_seconds)},
            )


# Pre-configured limiters
auth_limiter = RateLimiter(max_requests=10, window_seconds=60)       # 登录、注册：每个 IP 每分钟 10 次
login_fail_limiter = RateLimiter(max_requests=20, window_seconds=900)  # 同一账号 15 分钟内最多 20 次密码错误
recovery_limiter = RateLimiter(max_requests=5, window_seconds=900)   # 恢复密钥重置密码：每个 IP 15 分钟 5 次
ai_limiter = RateLimiter(max_requests=20, window_seconds=60)
upload_limiter = RateLimiter(max_requests=5, window_seconds=60)
apply_limiter = RateLimiter(max_requests=5, window_seconds=3600)     # 科研孵化圈申请：每个 IP 每小时 5 次
github_limiter = RateLimiter(max_requests=30, window_seconds=60)     # GitHub 搜索代理：每个 IP 每分钟 30 次
_LIMITERS = (auth_limiter, login_fail_limiter, recovery_limiter, ai_limiter, upload_limiter, apply_limiter, github_limiter)


class DailyQuota:
    """按天（UTC）计数的额度：global_limit 是全站每天的上限，per_key_limit 是每个访客每天的上限，0 表示不限。"""

    MAX_KEYS = 20_000

    def __init__(self, global_limit: int, per_key_limit: int):
        self.global_limit = global_limit
        self.per_key_limit = per_key_limit
        self._day = ""
        self._total = 0
        self._per_key: dict = {}
        self._lock = threading.Lock()

    def take(self, key: str) -> Optional[str]:
        """记一次使用；额度已用完时不计数，返回给用户的提示，否则返回 None。"""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        with self._lock:
            if today != self._day:
                self._day, self._total, self._per_key = today, 0, {}
            if self.global_limit and self._total >= self.global_limit:
                return "今天的 AI 助教额度已经用完了，明天再来吧～"
            used = self._per_key.get(key, 0)
            if self.per_key_limit and used >= self.per_key_limit:
                return "你今天的提问次数已达上限，明天再来吧～"
            self._total += 1
            if key in self._per_key or len(self._per_key) < self.MAX_KEYS:
                self._per_key[key] = used + 1
            return None


# Background cleanup every 5 minutes
def _start_cleanup():
    def _cleanup_loop():
        while True:
            time.sleep(300)
            for limiter in _LIMITERS:
                limiter.cleanup()
    t = threading.Thread(target=_cleanup_loop, daemon=True)
    t.start()


_start_cleanup()


# ============================================================
# 3. Secure filename - prevent path injection
# ============================================================
# Control character ranges (ordinal values)
_CONTROL_CHARS = set(range(0, 32)) | set(range(127, 160))


def secure_filename(filename: str) -> str:
    """Sanitize a filename to prevent path traversal attacks."""
    if not filename:
        return 'unnamed_file'
    # Remove any path component
    filename = Path(filename).name
    # Remove null bytes and control characters
    filename = ''.join(c for c in filename if ord(c) >= 32 and ord(c) not in range(127, 160))
    # Normalize unicode
    try:
        filename = unicodedata.normalize('NFKD', filename)
    except Exception:
        pass
    # Remove leading/trailing dots, spaces, dashes
    filename = filename.strip('. _-')
    if not filename:
        return 'unnamed_file'
    # Limit length
    if len(filename) > 200:
        name, ext = os.path.splitext(filename)
        filename = name[:195] + ext
    return filename


# ============================================================
# 4. Security headers middleware
# ============================================================
# 不影响现有页面的内联脚本和 CDN 资源，只限制最容易被利用的几项：
# 禁止被其他网站嵌入（点击劫持）、禁止 <base> 改写相对地址、禁止插件内容、表单只能提交到本站
_CSP = "frame-ancestors 'self'; base-uri 'self'; object-src 'none'; form-action 'self'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '0'   # 旧浏览器的 XSS 过滤器本身会引入漏洞，现代做法是关闭，依靠 CSP 与转义
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        # 只在 HTTPS 下生效；浏览器通过 Render 的 HTTPS 访问本站
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        if 'content-security-policy' not in response.headers:   # 路由自己设置的 CSP（如页面预览的沙箱）优先
            response.headers['Content-Security-Policy'] = _CSP
        # Remove server signature (use del with fallback)
        for header in ('Server', 'X-Powered-By'):
            try:
                del response.headers[header]
            except (KeyError, AttributeError):
                pass
        return response


# ============================================================
# 5. Request body size limit
# ============================================================
MB = 1024 * 1024
_UPLOAD_PATH = re.compile(r"^/api/v1/(admin/content/files|resources/\d+/upload)$")
UPLOAD_BODY_LIMIT = 110 * MB   # 管理后台上传文件（单个文件上限 50 MB）
ADMIN_BODY_LIMIT = 10 * MB     # 管理后台保存页面、学习资源等
DEFAULT_BODY_LIMIT = 1 * MB    # 其他所有请求


class _BodyTooLarge(Exception):
    pass


def body_limit_for(path: str) -> int:
    if _UPLOAD_PATH.match(path):
        return UPLOAD_BODY_LIMIT
    if path.startswith("/api/v1/admin/"):
        return ADMIN_BODY_LIMIT
    return DEFAULT_BODY_LIMIT


class BodySizeLimitMiddleware:
    """限制请求体大小，防止超大请求把内存或临时磁盘撑满。

    FastAPI 会先读完整个请求体、再做登录校验，所以没有登录的人也能向任何接口发送巨大的请求。
    这里在读取请求体之前就按 Content-Length 拒绝，并在读取过程中计数（应对没有 Content-Length 的分块上传）。
    上传接口允许较大的请求体，但必须先带上管理员的登录令牌，否则直接拒绝、不读取请求体。
    """

    def __init__(self, app, admin_check=None):
        self.app = app
        self.admin_check = admin_check   # async (authorization_header) -> bool

    async def _reject(self, send, status_code: int, detail: str):
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": status_code,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        limit = body_limit_for(path)
        too_large = f"请求内容太大（上限 {limit // MB} MB）"
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is not None:
            try:
                length = int(length)
            except ValueError:
                return await self._reject(send, 400, "请求格式错误")
            if length > limit:
                return await self._reject(send, 413, too_large)
        if limit > DEFAULT_BODY_LIMIT and (length is None or length > DEFAULT_BODY_LIMIT) and _UPLOAD_PATH.match(path):
            auth = headers.get(b"authorization", b"").decode("latin-1")
            if not (self.admin_check and await self.admin_check(auth)):
                return await self._reject(send, 401, "请先以管理员身份登录")

        received = 0
        started = False    # 应用已经开始回复
        rejected = False   # 已经由这里回复了 413

        async def limited_receive():
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # 直接回复 413 并中断应用读取请求体。中断用的异常会被中间件包装、被 FastAPI 改写成 400，
                    # 所以不能指望它变成 413；应用之后发出的响应在 guarded_send 里丢弃
                    if not started and not rejected:
                        rejected = True
                        await self._reject(send, 413, too_large)
                    raise _BodyTooLarge()
            return message

        async def guarded_send(message):
            nonlocal started
            if rejected:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not rejected:
                raise
