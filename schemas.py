"""Pydantic schemas for API request/response validation."""

import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

# 用户提交的文本都限制长度：数据库列本身有长度上限（Postgres 超长会报错），也防止有人塞进超大内容
EMAIL_MAX = 200
PASSWORD_MAX = 128

EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
USERNAME_RE = re.compile(r"^[\w.\-]{2,32}$")   # \w 含中文、字母、数字和下划线
# 控制字符，以及零宽字符、改变文字方向的不可见字符（可以用来伪装成别人的名字）
_INVISIBLE_RE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁠-⁩﻿]")
_INVISIBLE_MULTILINE_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏ -‮⁠-⁩﻿]")


def clean_text(value: Optional[str], multiline: bool = False) -> str:
    """去掉首尾空白和不可见字符；multiline=True 时保留换行和制表符。"""
    pattern = _INVISIBLE_MULTILINE_RE if multiline else _INVISIBLE_RE
    return pattern.sub("", value or "").strip()


# ── Category ──────────────────────────────────────────────

class CategoryOut(BaseModel):
    id: int
    name: str
    slug: str
    description: str
    icon: str
    sort_order: int
    resource_count: int = 0

    model_config = {"from_attributes": True}


# ── Tag ───────────────────────────────────────────────────

class TagOut(BaseModel):
    id: int
    name: str
    slug: str
    resource_count: int = 0

    model_config = {"from_attributes": True}


# ── Resource ──────────────────────────────────────────────

class ResourceListItem(BaseModel):
    id: int
    title: str
    slug: str
    description: str
    category_slug: str = ""
    category_name: str = ""
    file_type: str = ""
    file_size: str = ""
    author: str = ""
    difficulty: int = 1
    view_count: int = 0
    download_count: int = 0
    is_featured: bool = False
    tags: list[TagOut] = []
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ResourceDetail(BaseModel):
    id: int
    title: str
    slug: str
    description: str
    content: str
    category_slug: str = ""
    category_name: str = ""
    file_url: str = ""
    file_type: str = ""
    file_size: str = ""
    author: str = ""
    source: str = ""
    difficulty: int = 1
    view_count: int = 0
    download_count: int = 0
    is_featured: bool = False
    tags: list[TagOut] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ResourceListResponse(BaseModel):
    items: list[ResourceListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── P1: Auth & User schemas ────────────────────────────

class UserRegister(BaseModel):
    username: str = Field(max_length=32)
    email: str = Field(max_length=EMAIL_MAX)
    password: str = Field(max_length=PASSWORD_MAX)
    display_name: Optional[str] = Field(None, max_length=50)


class UserLogin(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserOut"


class RefreshRequest(BaseModel):
    refresh_token: str = Field(max_length=2048)


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    display_name: str
    avatar_url: str
    is_admin: bool
    subscription: str = "free"
    is_elite: bool = False
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=50)
    avatar_url: Optional[str] = Field(None, max_length=500)
    email: Optional[str] = Field(None, max_length=EMAIL_MAX)


# ── P1: Favorite schemas ───────────────────────────────

class FavoriteOut(BaseModel):
    resource_id: int
    resource_title: str = ""
    resource_slug: str = ""
    category_name: str = ""
    description: str = ""
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class FavoriteCheck(BaseModel):
    resource_id: int
    is_favorited: bool


class FavoriteListResponse(BaseModel):
    items: list[FavoriteOut]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── P1: Progress schemas ───────────────────────────────

class ProgressUpdate(BaseModel):
    status: str = Field("in_progress", pattern="^(not_started|in_progress|completed)$")
    progress_percent: int = 0
    notes: Optional[str] = Field(None, max_length=5000)


class ProgressOut(BaseModel):
    id: int
    resource_id: int
    resource_title: str = ""
    resource_slug: str = ""
    category_name: str = ""
    status: str
    progress_percent: int
    notes: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Elite Matrix: Application schemas ────────────────────

class EliteApplyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    email: str = Field(max_length=EMAIL_MAX)
    school: str = Field(min_length=1, max_length=100)
    github: str = Field("", max_length=100)
    field: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)


class EliteApplicationOut(BaseModel):
    id: int
    name: str
    email: str
    school: str
    github: str = ""
    field: str
    reason: str
    status: str
    user_id: Optional[int] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EliteReviewRequest(BaseModel):
    action: str = Field(max_length=20)  # "approve" or "reject"
