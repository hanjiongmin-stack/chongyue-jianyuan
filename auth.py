"""JWT authentication utilities for 崇岳鉴渊."""

import os
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
from security import get_secret_key

# -- Security config --
SECRET_KEY = get_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


# -- Password utilities --
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# -- Token utilities --
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access", "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh", "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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


# -- Auth dependency --
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的令牌类型",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if token has been revoked
    jti = payload.get("jti")
    if jti and is_token_blacklisted(jti, db):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = int(user_id_str)

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# -- Optional auth --
async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if credentials is None:
        return None

    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        return None

    # Check blacklist
    jti = payload.get("jti")
    if jti and is_token_blacklisted(jti, db):
        return None

    user_id_str = payload.get("sub")
    if user_id_str is None:
        return None

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        return None

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        return None

    return user
