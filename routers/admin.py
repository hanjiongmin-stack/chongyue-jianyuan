"""Admin routes: user management + elite application review."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from database import get_db
from models import User, EliteApplication
from schemas import EliteApplicationOut, EliteReviewRequest
from auth import get_current_user, hash_password

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ── Schemas ──────────────────────────────────────────────

class AdminUserOut(BaseModel):
    id: int
    username: str
    email: str
    display_name: str
    is_active: bool
    is_admin: bool
    subscription: str
    is_elite: bool
    subscription_expires: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AdminUserUpdate(BaseModel):
    subscription: Optional[str] = None       # free / start / pro / elite
    is_elite: Optional[bool] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    subscription_expires: Optional[str] = None  # ISO date string or empty


class PasswordReset(BaseModel):
    new_password: str


# ── Dependency ───────────────────────────────────────────

def require_admin(current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


# ── Routes ───────────────────────────────────────────────

@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """列出所有用户（仅管理员）"""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [AdminUserOut.model_validate(u) for u in users]


@router.put("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int,
    body: AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """更新用户状态（订阅、精英矩阵、禁用/启用）"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if body.subscription is not None:
        if body.subscription not in ("free", "start", "pro", "elite"):
            raise HTTPException(status_code=422, detail="无效的订阅类型")
        user.subscription = body.subscription
    if body.is_elite is not None:
        user.is_elite = body.is_elite
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.is_admin is not None:
        user.is_admin = body.is_admin
    if body.subscription_expires is not None:
        if body.subscription_expires.strip():
            try:
                user.subscription_expires = datetime.fromisoformat(body.subscription_expires.strip())
            except ValueError:
                raise HTTPException(status_code=422, detail="日期格式无效 (YYYY-MM-DD)")
        else:
            user.subscription_expires = None

    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return AdminUserOut.model_validate(user)


@router.put("/users/{user_id}/password")
def reset_password(
    user_id: int,
    body: PasswordReset,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """管理员重置用户密码"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=422, detail="密码至少6个字符")

    user.hashed_password = hash_password(body.new_password)
    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": f"用户 {user.username} 的密码已重置", "status": "ok"}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """删除用户（不能删除自己）"""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    username = user.username
    db.delete(user)
    db.commit()
    return {"message": f"用户 {username} 已删除", "status": "ok"}


# ── Elite Matrix: Application Review ───────────────────────

@router.get("/elite-applications", response_model=list[EliteApplicationOut])
def list_elite_applications(
    status: Optional[str] = Query(None, description="Filter: pending / approved / rejected"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """列出所有精英矩阵申请（仅管理员）"""
    q = db.query(EliteApplication)
    if status and status in ("pending", "approved", "rejected"):
        q = q.filter(EliteApplication.status == status)
    apps = q.order_by(EliteApplication.created_at.desc()).all()
    return [EliteApplicationOut.model_validate(a) for a in apps]


@router.post("/elite-applications/{app_id}/review", response_model=EliteApplicationOut)
def review_elite_application(
    app_id: int,
    body: EliteReviewRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """审批精英矩阵申请：approve 或 reject"""
    app = db.query(EliteApplication).filter(EliteApplication.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="申请不存在")

    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="action 必须是 approve 或 reject")

    app.status = "approved" if body.action == "approve" else "rejected"
    app.reviewed_by = admin.id
    app.reviewed_at = datetime.now(timezone.utc)

    # If approved, set user's is_elite flag
    if body.action == "approve":
        # Try to find matching user by email
        user = db.query(User).filter(User.email == app.email).first()
        if user:
            user.is_elite = True
            user.subscription = "elite"
            user.updated_at = datetime.now(timezone.utc)
        # Also link application to user if found
        if user:
            app.user_id = user.id

    db.commit()
    db.refresh(app)
    return EliteApplicationOut.model_validate(app)
