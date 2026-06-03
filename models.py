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

    resources = relationship("Resource", back_populates="category", lazy="selectin")

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

    resources = relationship("Resource", secondary=resource_tags, back_populates="tags", lazy="selectin")

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    favorites = relationship("Favorite", back_populates="user", lazy="selectin",
                             cascade="all, delete-orphan")
    progress_items = relationship("Progress", back_populates="user", lazy="selectin",
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


# -- Security: Token blacklist --
