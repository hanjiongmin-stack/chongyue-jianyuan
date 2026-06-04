"""SQLite database engine and session management for 崇岳鉴渊."""

import json
import logging
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Render 免费实例只有 /tmp 可写，本地保持 data/ 目录
if os.environ.get("RENDER"):
    DB_PATH = Path("/tmp/chongyue.db")
else:
    DB_PATH = BASE_DIR / "data" / "chongyue.db"
    DB_PATH.parent.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

# Enable WAL mode for better concurrent read/write performance
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

logger = logging.getLogger("database")


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


import re


def _slugify(text: str) -> str:
    """Generate a URL-safe slug. Handles both Chinese and ASCII names."""
    # Lowercase ASCII chars, keep Chinese as-is, collapse spaces to hyphens
    slug = text.strip().lower().replace(" ", "-")
    return slug or "untitled"


def auto_seed(db=None):
    """Seed categories, tags, resources, and admin user if database is empty.
    Safe to call multiple times — only seeds empty tables."""
    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        from models import Category, Tag, Resource, User
        from auth import hash_password

        # --- Seed admin user (if no admin exists) ---
        if db.query(User).filter(User.is_admin == True).count() == 0:
            # 优先用已存在的第一个用户提权，否则创建 admin 账号
            first_user = db.query(User).first()
            if first_user:
                first_user.is_admin = True
                db.commit()
                logger.info(f"Promoted {first_user.username} to admin")
            else:
                admin = User(
                    username="admin",
                    email="hanjiongmin@hotmail.com",
                    hashed_password=hash_password("admin123"),
                    display_name="管理员",
                    is_admin=True,
                    subscription="elite",
                    is_elite=True,
                )
                db.add(admin)
                db.commit()
                logger.info("Seeded admin user (admin / admin123)")

        # --- Seed categories ---
        if db.query(Category).count() == 0:
            seed_path = BASE_DIR / "seed_categories_tags.json"
            if seed_path.exists():
                with open(seed_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for c in data.get("categories", []):
                    db.add(Category(
                        name=c["name"], slug=c["slug"],
                        description=c.get("description", ""),
                        sort_order=c.get("sort_order", 0),
                    ))
                db.commit()
                logger.info(f"Seeded {len(data.get('categories', []))} categories")

        # --- Seed tags ---
        if db.query(Tag).count() == 0:
            seed_path = BASE_DIR / "seed_categories_tags.json"
            if seed_path.exists():
                with open(seed_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for t in data.get("tags", []):
                    name = t["name"]
                    slug = t.get("slug") or _slugify(name)
                    db.add(Tag(name=name, slug=slug))
                db.commit()
                logger.info(f"Seeded {len(data.get('tags', []))} tags")

        # --- Seed resources ---
        if db.query(Resource).count() == 0:
            seed_path = BASE_DIR / "seed_resources.json"
            if seed_path.exists():
                with open(seed_path, "r", encoding="utf-8") as f:
                    resources = json.load(f)
                cat_map = {c.slug: c for c in db.query(Category).all()}
                tag_map = {t.name: t for t in db.query(Tag).all()}
                for rd in resources:
                    cat = cat_map.get(rd["category_slug"])
                    if cat is None:
                        continue
                    r = Resource(
                        title=rd["title"], slug=rd["slug"],
                        description=rd.get("description", ""),
                        content=rd.get("content", ""),
                        category_id=cat.id,
                        author=rd.get("author", ""),
                        source=rd.get("source", ""),
                        file_type=rd.get("file_type", ""),
                        file_size=rd.get("file_size", ""),
                        difficulty=rd.get("difficulty", 1),
                        is_featured=rd.get("is_featured", False),
                    )
                    db.add(r)
                    # Attach tags
                    tag_names = rd.get("tag_names", [])
                    tag_objs = [tag_map[tn] for tn in tag_names if tn in tag_map]
                    r.tags = tag_objs
                db.commit()
                logger.info(f"Seeded {len(resources)} resources")
    finally:
        if own_db:
            db.close()


def init_db():
    """Create all tables and seed initial data. Call once at startup."""
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    auto_seed()
