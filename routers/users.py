"""User profile, favorites, and progress routes."""

import math
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models import User, Resource, Favorite, Progress
from schemas import (
    UserOut, UserUpdate,
    FavoriteOut, FavoriteCheck, FavoriteListResponse,
    ProgressUpdate, ProgressOut,
    EMAIL_RE, PASSWORD_MAX, clean_text,
)
from auth import get_current_user, verify_password, hash_password, password_problem, revoke_all_tokens
from security import auth_limiter

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)


def _safe_avatar_url(url: str) -> bool:
    """头像只允许 https 地址或本站路径：javascript:、data: 之类的地址一旦被页面当作链接或图片使用就可能执行脚本。"""
    if not url:
        return True
    if any(c.isspace() or c in "\"'<>\\`" for c in url):
        return False
    return url.startswith("https://") or (url.startswith("/") and not url.startswith("//"))


@router.put("/me", response_model=UserOut)
def update_me(
    body: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.display_name is not None:
        name = clean_text(body.display_name)
        if not name:
            raise HTTPException(status_code=422, detail="显示名称不能为空")
        current_user.display_name = name
    if body.avatar_url is not None:
        url = body.avatar_url.strip()
        if not _safe_avatar_url(url):
            raise HTTPException(status_code=422, detail="头像地址必须是 https:// 开头的图片链接")
        current_user.avatar_url = url
    if body.email is not None:
        email = body.email.strip().lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(status_code=422, detail="请输入有效的邮箱地址")
        # Check uniqueness
        existing = db.query(User).filter(User.email == email, User.id != current_user.id).first()
        if existing:
            raise HTTPException(status_code=409, detail="邮箱已被其他账号使用")
        current_user.email = email
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="邮箱已被其他账号使用")
    db.refresh(current_user)
    return UserOut.model_validate(current_user)


class PasswordChange(BaseModel):
    old_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=PASSWORD_MAX)


@router.put("/me/password")
def change_password(
    request: Request,
    body: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用户自行修改密码（修改后所有设备都需要重新登录）"""
    auth_limiter.limit(request)   # 防止拿到登录状态的人在这里反复猜原密码
    if not verify_password(body.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(status_code=422, detail="新" + problem)
    if body.old_password == body.new_password:
        raise HTTPException(status_code=422, detail="新密码不能与原密码相同")

    current_user.hashed_password = hash_password(body.new_password)
    revoke_all_tokens(current_user)   # 之前签发的令牌全部作废（包括可能被别人拿到的）
    current_user.updated_at = datetime.now(timezone.utc)
    db.commit()
    # WAL checkpoint: ensure write is flushed to disk immediately（仅 SQLite）
    if db.get_bind().dialect.name == "sqlite":
        try:
            from sqlalchemy import text
            db.execute(text("PRAGMA wal_checkpoint(FULL)"))
            db.commit()
        except Exception:
            pass
    return {"message": "密码已更新，请重新登录", "status": "ok"}


@router.get("/me/favorites", response_model=FavoriteListResponse)
def list_favorites(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id)
        .order_by(Favorite.created_at.desc())
    )
    total = query.count()
    total_pages = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size
    favs = query.offset(offset).limit(page_size).all()

    items = []
    for fav in favs:
        r = fav.resource
        items.append(FavoriteOut(
            resource_id=r.id,
            resource_title=r.title,
            resource_slug=r.slug,
            category_name=r.category.name if r.category else "",
            description=r.description or "",
            created_at=fav.created_at,
        ))

    return FavoriteListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/me/favorites/{resource_id}/check", response_model=FavoriteCheck)
def check_favorite(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fav = (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id, Favorite.resource_id == resource_id)
        .first()
    )
    return FavoriteCheck(resource_id=resource_id, is_favorited=fav is not None)


@router.post("/me/favorites/{resource_id}", response_model=FavoriteCheck, status_code=201)
def add_favorite(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="资源不存在")

    existing = (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id, Favorite.resource_id == resource_id)
        .first()
    )
    if existing:
        return FavoriteCheck(resource_id=resource_id, is_favorited=True)

    fav = Favorite(user_id=current_user.id, resource_id=resource_id)
    db.add(fav)
    db.commit()

    resource.download_count = (resource.download_count or 0) + 1
    db.commit()

    return FavoriteCheck(resource_id=resource_id, is_favorited=True)


@router.delete("/me/favorites/{resource_id}", response_model=FavoriteCheck)
def remove_favorite(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fav = (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id, Favorite.resource_id == resource_id)
        .first()
    )
    if not fav:
        return FavoriteCheck(resource_id=resource_id, is_favorited=False)

    db.delete(fav)
    db.commit()
    return FavoriteCheck(resource_id=resource_id, is_favorited=False)


@router.get("/me/progress", response_model=list[ProgressOut])
def list_progress(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = (
        db.query(Progress)
        .filter(Progress.user_id == current_user.id)
        .order_by(Progress.updated_at.desc())
        .all()
    )
    result = []
    for p in items:
        r = p.resource
        result.append(ProgressOut(
            id=p.id,
            resource_id=p.resource_id,
            resource_title=r.title if r else "",
            resource_slug=r.slug if r else "",
            category_name=r.category.name if r and r.category else "",
            status=p.status,
            progress_percent=p.progress_percent or 0,
            notes=p.notes or "",
            started_at=p.started_at,
            completed_at=p.completed_at,
            updated_at=p.updated_at,
        ))
    return result


@router.get("/me/progress/{resource_id}", response_model=ProgressOut)
def get_progress(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = (
        db.query(Progress)
        .filter(Progress.user_id == current_user.id, Progress.resource_id == resource_id)
        .with_for_update()
        .first()
    )
    if not p:
        raise HTTPException(status_code=404, detail="暂无学习记录")

    r = p.resource
    return ProgressOut(
        id=p.id,
        resource_id=p.resource_id,
        resource_title=r.title if r else "",
        resource_slug=r.slug if r else "",
        category_name=r.category.name if r and r.category else "",
        status=p.status,
        progress_percent=p.progress_percent or 0,
        notes=p.notes or "",
        started_at=p.started_at,
        completed_at=p.completed_at,
        updated_at=p.updated_at,
    )


@router.post("/me/progress/{resource_id}", response_model=ProgressOut)
def set_progress(
    resource_id: int,
    body: ProgressUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="资源不存在")

    p = (
        db.query(Progress)
        .filter(Progress.user_id == current_user.id, Progress.resource_id == resource_id)
        .with_for_update()
        .first()
    )

    now = datetime.now(timezone.utc)

    if not p:
        p = Progress(
            user_id=current_user.id,
            resource_id=resource_id,
            started_at=now if body.status in ("in_progress", "completed") else None,
        )
        db.add(p)

    p.status = body.status
    p.progress_percent = max(0, min(100, body.progress_percent))

    if body.notes is not None:
        p.notes = body.notes

    if body.status == "completed" and not p.completed_at:
        p.completed_at = now
        p.progress_percent = 100
    elif body.status != "completed":
        p.completed_at = None

    if body.status == "in_progress" and not p.started_at:
        p.started_at = now

    p.updated_at = now
    db.commit()
    db.refresh(p)

    r = p.resource
    return ProgressOut(
        id=p.id,
        resource_id=p.resource_id,
        resource_title=r.title if r else "",
        resource_slug=r.slug if r else "",
        category_name=r.category.name if r and r.category else "",
        status=p.status,
        progress_percent=p.progress_percent or 0,
        notes=p.notes or "",
        started_at=p.started_at,
        completed_at=p.completed_at,
        updated_at=p.updated_at,
    )
