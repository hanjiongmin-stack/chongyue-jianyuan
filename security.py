"""Security utilities for ChongYue JianYuan - rate limiter, secure filenames, security headers."""

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


def get_secret_key() -> str:
    """Get SECRET_KEY from env, or load from .secret_key file, or generate and warn."""
    key = os.environ.get('CYJY_SECRET_KEY')
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
class RateLimiter:
    """Simple in-memory rate limiter with per-client tracking."""

    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients = {}
        self._lock = threading.Lock()

    def _get_client_key(self, request: Request) -> str:
        ip = request.client.host if request.client else 'unknown'
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:12]
        return ip_hash + ':' + request.url.path

    def check(self, request: Request) -> bool:
        key = self._get_client_key(request)
        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            timestamps = self._clients.get(key, [])
            timestamps = [t for t in timestamps if t > window_start]
            if len(timestamps) >= self.max_requests:
                self._clients[key] = timestamps
                return False
            timestamps.append(now)
            self._clients[key] = timestamps
            return True

    def cleanup(self):
        now = time.time()
        window_start = now - self.window_seconds
        with self._lock:
            expired_keys = []
            for key, timestamps in self._clients.items():
                timestamps = [t for t in timestamps if t > window_start]
                if not timestamps:
                    expired_keys.append(key)
                else:
                    self._clients[key] = timestamps
            for key in expired_keys:
                del self._clients[key]

    def limit(self, request: Request):
        if not self.check(request):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail='Too many requests. Try again later.',
                headers={'Retry-After': str(self.window_seconds)},
            )


# Pre-configured limiters
auth_limiter = RateLimiter(max_requests=10, window_seconds=60)
ai_limiter = RateLimiter(max_requests=20, window_seconds=60)
upload_limiter = RateLimiter(max_requests=5, window_seconds=60)


# Background cleanup every 5 minutes
def _start_cleanup():
    def _cleanup_loop():
        while True:
            time.sleep(300)
            auth_limiter.cleanup()
            ai_limiter.cleanup()
            upload_limiter.cleanup()
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
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        # Remove server signature (use del with fallback)
        for header in ('Server', 'X-Powered-By'):
            try:
                del response.headers[header]
            except (KeyError, AttributeError):
                pass
        return response
