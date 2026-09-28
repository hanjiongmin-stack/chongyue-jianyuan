"""Auth routes: register, login, refresh, logout."""

import hashlib
import logging
import os as _os
import secrets as _secrets
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db, ON_RENDER, DEFAULT_ADMIN_PASSWORD
from models import User
from schemas import (
    UserRegister, UserLogin, TokenResponse, RefreshRequest, UserOut,
    EMAIL_RE, USERNAME_RE, PASSWORD_MAX, clean_text,
)
from auth import (
    hash_password, verify_password_or_dummy, password_problem,
    create_access_token, create_refresh_token, decode_token, token_claims,
    verify_token, revoke_all_tokens, blacklist_token, cleanup_expired_blacklist,
)
from security import auth_limiter, login_fail_limiter, recovery_limiter

logger = logging.getLogger("auth")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _issue_tokens(user: User) -> TokenResponse:
    claims = token_claims(user)
    return TokenResponse(
        access_token=create_access_token(claims),
        refresh_token=create_refresh_token(claims),
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(request: Request, body: UserRegister, db: Session = Depends(get_db)):
    # Rate limit
    auth_limiter.limit(request)

    # Validation
    username = body.username.strip()
    email = body.email.strip().lower()
    if len(username) < 2:
        raise HTTPException(status_code=422, detail="用户名至少2个字符")
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=422, detail="用户名只能包含中文、字母、数字和 _ . -，最多 32 个字符")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="请输入有效的邮箱地址")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    # Check uniqueness
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="用户名已被注册")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="邮箱已被注册")

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(body.password),
        display_name=clean_text(body.display_name) or username,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:   # 几乎同时有人用了相同的用户名或邮箱
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名或邮箱已被注册")
    db.refresh(user)
    return _issue_tokens(user)


@router.post("/login", response_model=TokenResponse)
def login(request: Request, body: UserLogin, db: Session = Depends(get_db)):
    # Rate limit
    auth_limiter.limit(request)

    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(status_code=422, detail="请输入用户名和密码")

    # 同一账号短时间内密码错误太多次就暂停登录，防止攻击者换着 IP 猜密码
    account_key = "u:" + hashlib.sha256(username.lower().encode()).hexdigest()[:16]
    if login_fail_limiter.count(account_key) >= login_fail_limiter.max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="这个账号密码错误次数过多，请 15 分钟后再试",
            headers={"Retry-After": str(login_fail_limiter.window_seconds)},
        )

    user = db.query(User).filter(User.username == username).first()
    # 用户不存在时也做同样耗时的校验，避免通过响应时间判断用户名是否已注册
    if not verify_password_or_dummy(body.password, user.hashed_password if user else None):
        login_fail_limiter.hit(account_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用",
        )
    if ON_RENDER and user.is_admin and body.password == DEFAULT_ADMIN_PASSWORD:
        # 默认密码写在公开的代码里，任何人都能用它登录管理后台
        logger.error(f"管理员 {user.username} 使用默认密码登录，已拒绝")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理员账号仍在使用公开的默认密码，为了安全已禁止登录。"
                   "请在 Render 的 Environment 中设置 CYJY_ADMIN_PASSWORD（至少 8 位），重新部署后用新密码登录。",
        )
    login_fail_limiter.reset(account_key)

    # Periodic cleanup of expired blacklisted tokens
    cleanup_expired_blacklist(db)
    return _issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    # 已注销、签发后改过密码，或用户已被禁用的刷新令牌都会被拒绝
    user, _ = verify_token(body.refresh_token, db, token_type="refresh")
    return _issue_tokens(user)


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = Field(None, max_length=2048)


@router.post("/logout")
def logout(
    request: Request,
    body: Optional[LogoutRequest] = None,
    db: Session = Depends(get_db),
):
    """注销请求头里的访问令牌，以及请求体里的刷新令牌（退出后它就不能再换取新的登录状态）。

    不要求访问令牌仍然有效：访问令牌只有 30 分钟，过期后退出也要能注销刷新令牌。
    令牌都经过签名校验，只能注销自己手里的有效令牌。
    """
    tokens = [(request.headers.get("Authorization", "").partition(" ")[2].strip(), "access")]
    if body and body.refresh_token:
        tokens.append((body.refresh_token, "refresh"))
    for token, token_type in tokens:
        payload = decode_token(token)
        if not payload or payload.get("type") != token_type:
            continue
        jti, exp = payload.get("jti"), payload.get("exp")
        try:
            user_id = int(payload.get("sub"))
        except (TypeError, ValueError):
            continue
        if jti and exp:
            blacklist_token(
                jti=jti,
                user_id=user_id,
                token_type=token_type,
                expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
                db=db,
            )
    return {"message": "已成功登出", "status": "ok"}


# ── 忘记密码 / 紧急重置 ──────────────────────────────

_RECOVERY_KEY = _os.environ.get("CYJY_RECOVERY_KEY", "")


class ResetRequest(BaseModel):
    username: str = Field(max_length=64)
    recovery_key: str = Field(max_length=256)
    new_password: str = Field(max_length=PASSWORD_MAX)


@router.post("/forgot-password")
def forgot_password(request: Request, body: ResetRequest, db: Session = Depends(get_db)):
    """通过恢复密钥重置密码（无需登录）。恢复密钥由环境变量 CYJY_RECOVERY_KEY 设置。"""
    if not _RECOVERY_KEY:
        raise HTTPException(status_code=501, detail="恢复密钥未配置，请联系管理员从后台重置")
    # 恢复密钥能重置任何账号的密码：限制尝试次数，并用恒定时间比较，防止被逐字猜出
    recovery_limiter.limit(request)
    if not _secrets.compare_digest(body.recovery_key.encode(), _RECOVERY_KEY.encode()):
        raise HTTPException(status_code=403, detail="恢复密钥错误")

    user = db.query(User).filter(User.username == body.username.strip()).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    user.hashed_password = hash_password(body.new_password)
    revoke_all_tokens(user)   # 之前登录的设备全部需要重新登录
    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": f"用户 {user.username} 的密码已重置", "status": "ok"}
