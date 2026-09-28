"""数据库引擎与会话管理。

默认使用本地 SQLite 文件。设置环境变量 DATABASE_URL 后改用外部 Postgres（例如 Neon 的免费数据库）：
Render 免费实例的磁盘是临时的，每次部署或闲置休眠后重启都会清空，SQLite 里的账号、收藏和学习进度会随之丢失。
"""

import json
import logging
import os
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _external_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    # 托管服务给出的连接串一般以 postgres:// 或 postgresql:// 开头，统一交给 psycopg 3 驱动
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _external_database_url()
if DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,   # 免费数据库会在空闲时断开连接，取用前先探测
        pool_recycle=300,
        # 关闭 psycopg 的自动预编译语句，兼容 Neon 等服务的连接池（PgBouncer 事务模式）
        connect_args={"prepare_threshold": None} if DATABASE_URL.startswith("postgresql+psycopg") else {},
    )
else:
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

IS_SQLITE = engine.dialect.name == "sqlite"
# 数据能否跨重启保留：外部数据库或本地 SQLite 文件可以；Render 上 /tmp 里的 SQLite 每次重启都会清空
PERSISTENT = not (IS_SQLITE and os.environ.get("RENDER"))

if IS_SQLITE:
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


def _unique_tag_slug(db, name: str) -> str:
    from models import Tag
    base = _slugify(name)
    slug, i = base, 2
    while db.query(Tag).filter(Tag.slug == slug).first() is not None:
        slug, i = f"{base}-{i}", i + 1
    return slug


def _migrate():
    """给已有的本地数据库补上后来新增的列（SQLite 的 create_all 不会修改已存在的表）。"""
    from sqlalchemy import inspect, text
    cols = {c["name"] for c in inspect(engine).get_columns("resources")}
    if "attachments" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE resources ADD COLUMN attachments TEXT DEFAULT ''"))
        logger.info("数据库迁移：resources 表新增 attachments 列")


def auto_seed(db=None):
    """创建管理员账号（仅在还没有管理员时），并按种子文件对齐分类、标签和学习资源。可重复调用。"""
    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        from models import User
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
                admin_pw = os.environ.get("CYJY_ADMIN_PASSWORD", "admin123")
                admin = User(
                    username="admin",
                    email="hanjiongmin@hotmail.com",
                    hashed_password=hash_password(admin_pw),
                    display_name="管理员",
                    is_admin=True,
                    subscription="elite",
                    is_elite=True,
                )
                db.add(admin)
                db.commit()
                logger.info(f"Seeded admin user (admin / {'*' * len(admin_pw)})")

        # --- 分类、标签、学习资源：按仓库里的种子文件对齐 ---
        try:
            sync_content(db)
        except Exception:
            # 对齐失败时保留数据库里现有的内容，不影响网站启动
            db.rollback()
            logger.exception("按种子文件对齐学习资源失败，继续使用数据库中现有的内容")
    finally:
        if own_db:
            db.close()


def _load_seed(name: str, default):
    path = BASE_DIR / name
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sync_content(db) -> None:
    """让数据库中的分类、标签和学习资源与种子文件一致。

    种子文件（seed_categories_tags.json、seed_resources.json）保存在 GitHub 仓库里，管理后台的修改也会写回这两个文件，
    所以它们是内容的准：每次启动都按它们新增、更新或删除资源。同一个 id 的资源原地更新，阅读数、下载数，
    以及用户对它的收藏和学习进度都保留；种子文件里已经删掉的资源，会连同相关的收藏、进度一起删除。
    """
    from models import Category, Tag, Resource

    ct = _load_seed("seed_categories_tags.json", {})
    cats = {c.slug: c for c in db.query(Category).all()}
    for c in ct.get("categories", []):
        cat = cats.get(c["slug"])
        if cat is None:
            cat = cats[c["slug"]] = Category(slug=c["slug"])
            db.add(cat)
        cat.name = c["name"]
        cat.description = c.get("description", "")
        cat.sort_order = c.get("sort_order", 0)

    tags = {t.name: t for t in db.query(Tag).all()}
    for t in ct.get("tags", []):
        if t["name"] not in tags:
            tags[t["name"]] = Tag(name=t["name"], slug=t.get("slug") or _unique_tag_slug(db, t["name"]))
            db.add(tags[t["name"]])
    db.flush()

    seed = _load_seed("seed_resources.json", None)
    if seed is None:
        db.commit()
        return
    existing = {r.id: r for r in db.query(Resource).all()}
    # 先删掉种子文件里已经没有的资源（收藏、学习进度和标签关联由外键 ON DELETE CASCADE 一并删除），
    # 再新增或更新，避免新资源沿用被删资源的 slug 时触发唯一约束
    seed_ids = {int(rd["id"]) for rd in seed if rd.get("id")}
    seed_slugs = {rd["slug"] for rd in seed if not rd.get("id")}
    removed = [r for rid, r in existing.items() if rid not in seed_ids and r.slug not in seed_slugs]
    for r in removed:
        db.delete(r)
        del existing[r.id]
    db.flush()
    by_slug = {r.slug: r for r in existing.values()}
    added = updated = 0
    for rd in seed:
        cat = cats.get(rd.get("category_slug"))
        if cat is None:
            continue
        rid = int(rd["id"]) if rd.get("id") else None
        r = existing.get(rid) if rid else by_slug.get(rd["slug"])
        if r is None:
            r = Resource()
            if rid:
                r.id = rid  # 保持资源 ID 稳定：/knowledge/{id} 链接、收藏和附件都依赖它
            db.add(r)
            added += 1
        fields = dict(
            title=rd["title"], slug=rd["slug"],
            description=rd.get("description", ""), content=rd.get("content", ""),
            category_id=cat.id, author=rd.get("author", ""), source=rd.get("source", ""),
            file_type=rd.get("file_type", ""), file_size=rd.get("file_size", ""),
            difficulty=rd.get("difficulty", 1), is_featured=rd.get("is_featured", False),
            status=rd.get("status", "published"),
            attachments=json.dumps(rd.get("attachments") or [], ensure_ascii=False),
        )
        changed = False
        for k, v in fields.items():
            if getattr(r, k) != v:
                setattr(r, k, v)
                changed = True
        # 标签（管理后台新建的标签不在 seed_categories_tags.json 中，按需创建）
        tag_objs = []
        for tn in rd.get("tag_names", []):
            tn = str(tn).strip()
            if not tn:
                continue
            if tn not in tags:
                tags[tn] = Tag(name=tn, slug=_unique_tag_slug(db, tn))
                db.add(tags[tn])
                db.flush()
            tag_objs.append(tags[tn])
        if [t.name for t in (r.tags or [])] != [t.name for t in tag_objs]:
            r.tags = tag_objs
            changed = True
        db.flush()
        if changed and r.id in existing:
            updated += 1
    db.commit()
    if engine.dialect.name == "postgresql":
        # 显式写入了 id，要把自增序列推到最大 id 之后，否则管理后台新建资源时会撞上已有 id
        db.execute(text("SELECT setval(pg_get_serial_sequence('resources', 'id'), "
                        "COALESCE((SELECT MAX(id) FROM resources), 0) + 1, false)"))
        db.commit()
    if added or updated or removed:
        logger.info(f"学习资源已与种子文件对齐：新增 {added}，更新 {updated}，删除 {len(removed)}")


def init_db():
    """Create all tables and seed initial data. Call once at startup."""
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate()
    auto_seed()
