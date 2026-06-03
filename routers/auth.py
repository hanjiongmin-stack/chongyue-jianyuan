"""Auth routes: register, login, refresh, logout."""

import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import get_db
from models import User, TokenBlacklist
from schemas import UserRegister, UserLogin, TokenResponse, RefreshRequest, UserOut
from auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user, cleanup_expired_blacklist,
)
from security import auth_limiter

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(request: Request, body: UserRegister, db: Session = Depends(get_db)):
    # Rate limit
    auth_limiter.limit(request)

    # Validation
    if not body.username or len(body.username.strip()) < 2:
        raise HTTPException(status_code=422, detail="用户名至少2个字符")
    if not body.email or not EMAIL_RE.match(body.email):
        raise HTTPException(status_code=422, detail="请输入有效的邮箱地址")
    if not body.password or len(body.password) < 6:
        raise HTTPException(status_code=422, detail="密码至少6个字符")

    # Check uniqueness
    if db.query(User).filter(User.username == body.username.strip()).first():
        raise HTTPException(status_code=409, detail="用户名已被注册")
    if db.query(User).filter(User.email == body.email.strip().lower()).first():
        raise HTTPException(status_code=409, detail="邮箱已被注册")

    user = User(
        username=body.username.strip(),
        email=body.email.strip().lower(),
        hashed_password=hash_password(body.password),
        display_name=body.display_name or body.username.strip(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(request: Request, body: UserLogin, db: Session = Depends(get_db)):
    # Rate limit
    auth_limiter.limit(request)

    if not body.username or not body.password:
        raise HTTPException(status_code=422, detail="请输入用户名和密码")

    user = db.query(User).filter(User.username == body.username.strip()).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用",
        )

    # Periodic cleanup of expired blacklisted tokens
    cleanup_expired_blacklist(db)

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的刷新令牌",
        )

    user_id = int(payload.get("sub"))
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
        )

    access_token = create_access_token({"sub": str(user.id)})
    new_refresh = create_refresh_token({"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        user=UserOut.model_validate(user),
    )


@router.post("/logout")
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke the current access token by adding its JTI to the blacklist."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "", 1)
    payload = decode_token(token)
    if payload:
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti and exp:
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
            from auth import blacklist_token
            blacklist_token(
                jti=jti,
                user_id=current_user.id,
                token_type="access",
                expires_at=expires_at,
                db=db,
            )
    return {"message": "已成功登出", "status": "ok"}
