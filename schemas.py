"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


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
    username: str
    email: str
    password: str
    display_name: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserOut"


class RefreshRequest(BaseModel):
    refresh_token: str


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
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    email: Optional[str] = None


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
    status: str = "in_progress"  # not_started / in_progress / completed
    progress_percent: int = 0
    notes: Optional[str] = None


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
