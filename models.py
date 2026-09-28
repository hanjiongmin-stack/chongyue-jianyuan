"""SQLAlchemy ORM models for 崇岳鉴渊."""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Table, Boolean, UniqueConstraint
)
from sqlalchemy.orm import relationship
from database import Base


resource_tags = Table(
    "resource_tags",
    Base.metadata,
    Column("resource_id", Integer, ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), default="")
    icon = Column(String(50), default="")
    sort_order = Column(Integer, default=0)

    # 反向集合按需加载：设成 selectin 的话，每读一个资源都会连带把同分类的全部资源（含正文）读出来
    resources = relationship("Resource", back_populates="category", lazy="select")

    def __repr__(self):
        return f"<Category {self.slug}>"


class Resource(Base):
    __tablename__ = "resources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(300), nullable=False)
    slug = Column(String(300), unique=True, nullable=False, index=True)
    description = Column(String(1000), default="")
    content = Column(Text, default="")               # Markdown body
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)
    file_url = Column(String(500), default="")
    file_type = Column(String(20), default="")
    file_size = Column(String(20), default="")
    author = Column(String(100), default="")
    source = Column(String(300), default="")
    cover_image = Column(String(500), default="")
    difficulty = Column(Integer, default=1)           # 1-5
    view_count = Column(Integer, default=0)
    download_count = Column(Integer, default=0)
    is_featured = Column(Boolean, default=False)
    status = Column(String(20), default="published")  # published / draft
    attachments = Column(Text, default="")            # JSON：[{key, name, size}]，文件保存在文件库
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    category = relationship("Category", back_populates="resources", lazy="selectin")
    tags = relationship("Tag", secondary=resource_tags, back_populates="resources", lazy="selectin")

    def __repr__(self):
        return f"<Resource {self.slug}>"


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)

    resources = relationship("Resource", secondary=resource_tags, back_populates="tags", lazy="select")

    def __repr__(self):
        return f"<Tag {self.slug}>"


# ── P1: User & progress models ─────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(200), unique=True, nullable=False, index=True)
    hashed_password = Column(String(200), nullable=False)
    display_name = Column(String(100), default="")
    avatar_url = Column(String(500), default="")
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    subscription = Column(String(20), default="free")    # free / start / pro / elite
    is_elite = Column(Boolean, default=False)             # 精英矩阵成员
    subscription_expires = Column(DateTime, nullable=True)
    token_version = Column(Integer, nullable=False, default=0, server_default="0")  # 修改密码时加一，旧令牌全部失效
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # 按需加载：每个登录请求都要读取用户，没必要连带读出全部收藏、学习进度和对应的资源正文
    favorites = relationship("Favorite", back_populates="user", lazy="select",
                             cascade="all, delete-orphan")
    progress_items = relationship("Progress", back_populates="user", lazy="select",
                                  cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username}>"


class Favorite(Base):
    __tablename__ = "favorites"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    resource_id = Column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="favorites", lazy="selectin")
    resource = relationship("Resource", lazy="selectin")

    def __repr__(self):
        return f"<Favorite user={self.user_id} resource={self.resource_id}>"


class Progress(Base):
    __tablename__ = "progress"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_id = Column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), default="not_started")  # not_started / in_progress / completed
    progress_percent = Column(Integer, default=0)
    notes = Column(Text, default="")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "resource_id", name="uq_user_resource_progress"),
    )

    user = relationship("User", back_populates="progress_items", lazy="selectin")
    resource = relationship("Resource", lazy="selectin")

    def __repr__(self):
        return f"<Progress user={self.user_id} resource={self.resource_id} status={self.status}>"


# ── App settings (key-value) ───────────────────────────
class AppSetting(Base):
    """少量需要跨重启保留的配置，例如未设置 CYJY_SECRET_KEY 时自动生成的登录签名密钥。"""
    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)


# ── Security: Token blacklist ──────────────────────────
class TokenBlacklist(Base):
    """Store revoked JWT tokens by JTI (JWT ID)."""
    __tablename__ = "token_blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    jti = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    token_type = Column(String(10), default="access")  # access / refresh
    expires_at = Column(DateTime, nullable=False)
    blacklisted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<TokenBlacklist jti={self.jti[:8]}... user={self.user_id}>"


# ── Elite Matrix: Applications ──────────────────────────

class EliteApplication(Base):
    """精英矩阵入圈申请表"""
    __tablename__ = "elite_applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    email = Column(String(200), nullable=False)
    school = Column(String(200), nullable=False)
    github = Column(String(200), default="")
    field = Column(String(100), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(20), default="pending")     # pending / approved / rejected
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    applicant = relationship("User", foreign_keys=[user_id], lazy="selectin")
    reviewer = relationship("User", foreign_keys=[reviewed_by], lazy="selectin")

    def __repr__(self):
        return f"<EliteApplication {self.name} status={self.status}>"


# -- Security: Token blacklist --
