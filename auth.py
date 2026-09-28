"""JWT authentication utilities for 崇岳鉴渊."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import User, TokenBlacklist
from schemas import PASSWORD_MAX
from security import get_secret_key

# -- Security config --
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30   # 刷新令牌每次使用都会换新，常来的用户会一直保持登录
MAX_TOKEN_LENGTH = 2048          # 本站签发的令牌只有几百字节，超长的直接拒绝
_secret_key: Optional[str] = None


def _secret() -> str:
    # 首次签发或校验令牌时再读取：未设置 CYJY_SECRET_KEY 时密钥可能保存在数据库里
    global _secret_key
    if _secret_key is None:
        _secret_key = get_secret_key()
    return _secret_key

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


# -- Password utilities --
PASSWORD_MIN = 6


def password_problem(password: str) -> Optional[str]:
    """新密码不符合要求时返回原因，符合时返回 None。"""
    if len(password) < PASSWORD_MIN:
        return f"密码至少{PASSWORD_MIN}个字符"
    if len(password) > PASSWORD_MAX:
        return f"密码不能超过{PASSWORD_MAX}个字符"
    return None


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


_dummy_hash: Optional[str] = None


def verify_password_or_dummy(plain: str, hashed: Optional[str]) -> bool:
    """用户不存在（hashed 为 None）时也做一次同样耗时的校验，避免通过响应时间判断用户名是否已注册。"""
    global _dummy_hash
    if hashed is None:
        if _dummy_hash is None:
            _dummy_hash = hash_password(secrets.token_urlsafe(16))
        verify_password(plain, _dummy_hash)
        return False
    return verify_password(plain, hashed)


# -- Token utilities --
def token_claims(user: User) -> dict:
    """令牌里记录用户 ID 和令牌版本号：修改或重置密码时版本号加一，之前签发的令牌随之全部失效。"""
    return {"sub": str(user.id), "ver": user.token_version or 0}


def revoke_all_tokens(user: User) -> None:
    user.token_version = (user.token_version or 0) + 1


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access", "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, _secret(), algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh", "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    if not token or len(token) > MAX_TOKEN_LENGTH:
        return None
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# -- Token blacklist --
def is_token_blacklisted(jti: str, db: Session) -> bool:
    """Check if a token JTI has been revoked."""
    return db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first() is not None


def blacklist_token(jti: str, user_id: int, token_type: str, expires_at: datetime, db: Session):
    """Revoke a token by adding its JTI to the blacklist."""
    existing = db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first()
    if existing:
        return
    entry = TokenBlacklist(
        jti=jti,
        user_id=user_id,
        token_type=token_type,
        expires_at=expires_at,
    )
    db.add(entry)
    db.commit()


def cleanup_expired_blacklist(db: Session):
    """Remove expired tokens from blacklist."""
    now = datetime.now(timezone.utc)
    db.query(TokenBlacklist).filter(TokenBlacklist.expires_at < now).delete()
    db.commit()


# -- Token verification --
def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_token(token: str, db: Session, token_type: str = "access") -> tuple[User, dict]:
    """校验令牌，返回 (用户, 令牌内容)。

    令牌无效或过期、类型不对、已注销、签发后用户改过密码，或用户不存在、已被禁用时抛出 401。
    """
    payload = decode_token(token)
    if payload is None:
        raise _unauthorized("登录已过期，请重新登录")
    if payload.get("type") != token_type:
        raise _unauthorized("无效的令牌类型")

    # Check if token has been revoked
    jti = payload.get("jti")
    if jti and is_token_blacklisted(jti, db):
        raise _unauthorized("令牌已失效，请重新登录")

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise _unauthorized("无效的令牌")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("用户不存在或已被禁用")
    if payload.get("ver", 0) != (user.token_version or 0):
        raise _unauthorized("密码已修改，请重新登录")
    return user, payload


def user_from_token(token: str, db: Session) -> Optional[User]:
    """访问令牌对应的用户；令牌无效时返回 None。"""
    try:
        return verify_token(token, db)[0]
    except HTTPException:
        return None


# -- Auth dependency --
# 普通函数（非 async）：FastAPI 会放到线程池里执行，数据库查询不会阻塞整个服务
def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthorized("请先登录")
    return verify_token(credentials.credentials, db)[0]


# -- Optional auth --
def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if credentials is None:
        return None
    return user_from_token(credentials.credentials, db)
