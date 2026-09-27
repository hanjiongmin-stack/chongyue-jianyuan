"""管理后台 · 内容管理：页面编辑、文件库、学习资源的增删改。

所有修改都通过 content_store 保存：线上配置了 CYJY_GITHUB_TOKEN 时提交到 GitHub 仓库
（附件保存在 Release「site-files」），本地开发时直接写入项目目录。
"""

import json
import mimetypes
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from content_store import ContentError, store
from database import BASE_DIR, get_db, _slugify
from models import Category, Resource, Tag, User
from partials import apply_partials
from routers.admin import require_admin

router = APIRouter(prefix="/api/v1/admin/content", tags=["admin-content"])
public_router = APIRouter(tags=["files"])

STATIC_DIR = BASE_DIR / "static"
SEED_RESOURCES = "seed_resources.json"
MAX_UPLOAD = 50 * 1024 * 1024

# 允许上传的文件类型。不接受 HTML / SVG / JS 等会在本站域名下执行脚本的格式。
ALLOWED_EXTS = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv", ".txt", ".md",
    ".json", ".py", ".ipynb", ".m", ".c", ".cpp", ".java", ".tex", ".bib",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".zip", ".rar", ".7z", ".mp4", ".webm", ".mp3", ".wav",
}
INLINE_TYPES = ("application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp",
                "video/mp4", "video/webm", "audio/mpeg", "audio/wav", "text/plain", "text/csv")


def _fail(e: ContentError):
    raise HTTPException(status_code=e.status, detail=str(e))


def clean_name(name: str) -> str:
    name = Path((name or "").replace("\\", "/")).name
    name = "".join(c for c in name if ord(c) >= 32 and not 127 <= ord(c) < 160)
    name = unicodedata.normalize("NFC", name).strip(". ")
    return (name or "file")[:180]


def preview_type(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return "image"
    if ext in (".txt", ".md", ".py", ".json", ".csv", ".m", ".c", ".cpp", ".java", ".tex", ".bib"):
        return "text"
    if ext in (".pptx", ".ppt"):
        return "pptx"
    if ext in (".mp4", ".webm"):
        return "video"
    if ext in (".mp3", ".wav"):
        return "audio"
    return "none"


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / 1024 / 1024:.1f}MB"


def file_url(key: str) -> str:
    return f"/files/{quote(key)}"


# ── 状态 ─────────────────────────────────────────────────

@router.get("/status")
def content_status(admin: User = Depends(require_admin)):
    return store.status()


# ── 页面编辑 ─────────────────────────────────────────────

PAGE_INFO = {
    "static/index.html": ("首页", "站点", "/"),
    "static/knowledge.html": ("学习资源库", "学习资源", "/knowledge"),
    "static/knowledge-detail.html": ("资源详情（模板）", "学习资源", "/knowledge/1"),
    "static/knowledge-base.html": ("多维知识库", "学习资源", "/knowledge-base"),
    "static/math.html": ("数学竞赛真题库", "学科板块", "/math/"),
    "static/math-hub.html": ("高等数学", "学科板块", "/math-hub"),
    "static/signals-and-systems.html": ("信号与系统", "学科板块", "/signals-and-systems"),
    "static/python-course.html": ("Python 数据分析", "学科板块", "/python-course"),
    "static/chemistry/index.html": ("高等化学 · 总览", "高等化学", "/chemistry"),
    "static/chemistry/organic.html": ("有机化学", "高等化学", "/chemistry/organic.html"),
    "static/chemistry/inorganic.html": ("无机化学", "高等化学", "/chemistry/inorganic.html"),
    "static/chemistry/physical.html": ("物理化学", "高等化学", "/chemistry/physical.html"),
    "static/chemistry/analytical.html": ("分析化学", "高等化学", "/chemistry/analytical.html"),
    "static/chemistry/biochemistry.html": ("生物化学", "高等化学", "/chemistry/biochemistry.html"),
    "static/ai-coding.html": ("AI 编程专区", "专区", "/ai-coding"),
    "static/research.html": ("科研孵化", "专区", "/research"),
    "static/testimonials.html": ("学长学姐说", "专区", "/testimonials"),
    "static/elite-matrix.html": ("精英矩阵", "专区", "/elite-matrix"),
    "static/pricing.html": ("平台通道 · 权益对比", "平台通道", "/pricing"),
    "static/pricing-start.html": ("溯熵新手池", "平台通道", "/pricing/start"),
    "static/pricing-pro.html": ("高能进阶舱", "平台通道", "/pricing/pro"),
    "static/pricing-elite.html": ("星辰科研孵化圈", "平台通道", "/pricing/elite"),
    "static/pricing-partner.html": ("校园合伙人", "平台通道", "/pricing/partner"),
    "static/login.html": ("登录 / 注册", "账户", "/login"),
    "static/profile.html": ("个人中心", "账户", "/profile"),
    "static/partials/nav.html": ("顶部导航（所有页面共用）", "公共片段", None),
    "static/partials/footer.html": ("页脚（所有页面共用）", "公共片段", None),
}
GROUP_ORDER = ["站点", "学习资源", "学科板块", "高等化学", "专区", "平台通道", "账户", "公共片段", "其他页面"]


def editable_pages() -> list:
    """可编辑页面：已登记的页面 + static/ 与 static/chemistry/ 下新增的 HTML（管理后台本身除外）。"""
    paths = set(p for p in PAGE_INFO if (BASE_DIR / p).exists())
    for f in list(STATIC_DIR.glob("*.html")) + list((STATIC_DIR / "chemistry").glob("*.html")):
        rel = f.relative_to(BASE_DIR).as_posix()
        if rel != "static/admin.html":
            paths.add(rel)
    out = []
    for p in paths:
        title, group, url = PAGE_INFO.get(p, (None, "其他页面", None))
        if title is None:
            m = re.search(r"<title>([^<|]+)", (BASE_DIR / p).read_text(encoding="utf-8", errors="ignore"))
            title = (m.group(1).strip() if m else Path(p).stem)
            url = "/chemistry/" + Path(p).name if p.startswith("static/chemistry/") else None
        out.append({"path": p, "title": title, "group": group, "url": url})
    order = {p: i for i, p in enumerate(PAGE_INFO)}  # 组内按登记顺序（总览在前），未登记的页面排在最后
    out.sort(key=lambda x: (GROUP_ORDER.index(x["group"]), order.get(x["path"], len(order)), x["path"]))
    return out


def check_page(path: str) -> str:
    if path not in {p["path"] for p in editable_pages()}:
        raise HTTPException(status_code=404, detail="页面不存在或不允许编辑")
    return path


class PageSave(BaseModel):
    path: str
    content: str
    sha: Optional[str] = None
    message: Optional[str] = Field(default=None, max_length=200)


class PagePreview(BaseModel):
    path: str
    content: str


@router.get("/pages")
def list_pages(admin: User = Depends(require_admin)):
    return editable_pages()


@router.get("/page")
async def get_page(path: str = Query(...), admin: User = Depends(require_admin)):
    check_page(path)
    try:
        return {"path": path, **(await store.read_text(path))}
    except ContentError as e:
        _fail(e)


@router.put("/page")
async def save_page(body: PageSave, admin: User = Depends(require_admin)):
    path = check_page(body.path)
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="页面内容不能为空")
    if "partials/" not in path and "</html>" not in body.content.lower():
        raise HTTPException(status_code=422, detail="页面缺少 </html> 结束标签，可能被意外截断，请检查后再保存")
    title = next((p["title"] for p in editable_pages() if p["path"] == path), path)
    message = f"content: 更新{title}（{admin.username} 通过管理后台）"
    if body.message and body.message.strip():
        message = f"content: {body.message.strip()}（{admin.username} 通过管理后台）"
    try:
        return await store.write_text(path, body.content, message, sha=body.sha)
    except ContentError as e:
        _fail(e)


@router.post("/page/preview")
def preview_page(body: PagePreview, admin: User = Depends(require_admin)):
    check_page(body.path)
    html = apply_partials(body.content)
    if body.path.startswith("static/partials/"):
        html = ("<!DOCTYPE html><html lang=\"zh-CN\" data-theme=\"dark\"><head><meta charset=\"UTF-8\">"
                + apply_partials("<!--cy:head-->") + "</head><body>" + html
                + apply_partials("<!--cy:tail-lite-->") + "</body></html>")
    return Response(content=html, media_type="text/html; charset=utf-8",
                     headers={"Content-Security-Policy": "sandbox allow-scripts"})


@router.get("/page/history")
async def page_history(path: str = Query(...), admin: User = Depends(require_admin)):
    check_page(path)
    try:
        return await store.history(path)
    except ContentError as e:
        _fail(e)


@router.get("/page/version")
async def page_version(path: str = Query(...), ref: str = Query(..., pattern=r"^[0-9a-f]{7,40}$"),
                       admin: User = Depends(require_admin)):
    check_page(path)
    try:
        return {"path": path, "ref": ref, "content": await store.read_text_at(path, ref)}
    except ContentError as e:
        _fail(e)


# ── 文件库 ───────────────────────────────────────────────

def media_out(item: dict) -> dict:
    return {**item, "url": file_url(item["key"]), "preview_type": preview_type(item["name"]),
            "size_text": human_size(item.get("size") or 0)}


async def read_upload(file: UploadFile) -> tuple:
    name = clean_name(file.filename)
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=422, detail=f"不支持上传 {ext or '无扩展名'} 文件")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail=f"单个文件不能超过 {MAX_UPLOAD // 1024 // 1024} MB")
    if not data:
        raise HTTPException(status_code=422, detail="文件是空的")
    return name, data, mimetypes.guess_type(name)[0] or "application/octet-stream"  # 类型按扩展名判断，不信任浏览器提供的值


@router.get("/files")
async def list_files(admin: User = Depends(require_admin)):
    try:
        return [media_out(i) for i in await store.media_list()]
    except ContentError as e:
        _fail(e)


@router.post("/files")
async def upload_files(files: list[UploadFile] = File(...), admin: User = Depends(require_admin)):
    out = []
    try:
        for f in files[:20]:
            name, data, ctype = await read_upload(f)
            out.append(media_out(await store.media_upload(name, data, ctype)))
    except ContentError as e:
        _fail(e)
    return out


@router.delete("/files/{key}")
async def delete_file(key: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    used = [r.title for r in db.query(Resource).all() if key in (r.attachments or "")]
    if used:
        raise HTTPException(status_code=409, detail="该文件是这些学习资源的附件，请先在资源中移除：" + "、".join(used[:5]))
    try:
        await store.media_delete(key)
    except ContentError as e:
        _fail(e)
    return {"ok": True}


@public_router.get("/files/{key}", include_in_schema=False)
async def serve_file(key: str, request: Request):
    """文件库中的文件。PDF、图片等在浏览器中直接打开，其他类型作为下载。"""
    if not re.fullmatch(r"[0-9a-f]+-[0-9a-f]+(\.[a-z0-9]{1,10})?", key):
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        item, src = await store.media_open(key, request.headers.get("range"))
    except ContentError as e:
        return JSONResponse({"detail": str(e)}, status_code=e.status)
    if not item:
        raise HTTPException(status_code=404, detail="文件不存在")
    ctype = item.get("content_type") or "application/octet-stream"
    inline = ctype.split(";")[0] in INLINE_TYPES and request.query_params.get("download") != "1"
    disp = f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(item['name'])}"
    safe = {"Content-Disposition": disp, "Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"}
    if isinstance(src, Path):
        return FileResponse(src, media_type=ctype, headers=safe)
    if src.status_code not in (200, 206, 304, 416):
        await src.aclose()
        return JSONResponse({"detail": "文件暂时无法读取，请稍后重试"}, status_code=502)
    headers = {k: src.headers[k] for k in ("content-length", "content-range", "etag", "last-modified") if k in src.headers}
    headers.update(safe)
    headers["Accept-Ranges"] = "bytes"
    return StreamingResponse(src.aiter_raw(), status_code=src.status_code, media_type=ctype,
                             headers=headers, background=BackgroundTask(src.aclose))


# ── 学习资源 ─────────────────────────────────────────────

class Attachment(BaseModel):
    key: str = Field(pattern=r"^[0-9a-f]+-[0-9a-f]+(\.[a-z0-9]{1,10})?$")
    name: str = Field(max_length=200)
    size: int = 0


class ResourceIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    slug: Optional[str] = Field(default=None, max_length=300)
    category_slug: str
    description: str = Field(default="", max_length=1000)
    content: str = Field(default="", max_length=200_000)
    author: str = Field(default="", max_length=100)
    source: str = Field(default="", max_length=300)
    file_type: str = Field(default="", max_length=20)
    file_size: str = Field(default="", max_length=20)
    difficulty: int = Field(default=1, ge=1, le=5)
    is_featured: bool = False
    status: str = Field(default="published", pattern=r"^(published|draft)$")
    tag_names: list[str] = Field(default_factory=list, max_length=20)
    attachments: list[Attachment] = Field(default_factory=list, max_length=50)


def attachments_of(r: Resource) -> list:
    try:
        return json.loads(r.attachments or "[]")
    except ValueError:
        return []


def resource_out(r: Resource, full: bool = False) -> dict:
    d = {
        "id": r.id, "title": r.title, "slug": r.slug,
        "category_slug": r.category.slug if r.category else "",
        "category_name": r.category.name if r.category else "",
        "status": r.status or "published", "is_featured": bool(r.is_featured),
        "difficulty": r.difficulty or 1, "author": r.author or "",
        "file_type": r.file_type or "", "file_size": r.file_size or "",
        "tag_names": [t.name for t in (r.tags or [])],
        "attachments": [{**a, "url": file_url(a["key"])} for a in attachments_of(r)],
        "view_count": r.view_count or 0,
        "updated_at": r.updated_at,
    }
    if full:
        d.update(description=r.description or "", content=r.content or "", source=r.source or "")
    return d


def export_resources(db: Session) -> str:
    """把全部学习资源导出为 seed_resources.json：线上实例每次启动都从这个文件重建资源。"""
    items = []
    for r in db.query(Resource).order_by(Resource.id).all():
        item = {
            "id": r.id, "title": r.title, "slug": r.slug,
            "description": r.description or "", "content": r.content or "",
            "category_slug": r.category.slug if r.category else "",
            "author": r.author or "", "source": r.source or "",
            "file_type": r.file_type or "", "file_size": r.file_size or "",
            "difficulty": r.difficulty or 1, "is_featured": bool(r.is_featured),
            "tag_names": [t.name for t in (r.tags or [])],
        }
        if (r.status or "published") != "published":
            item["status"] = r.status
        atts = attachments_of(r)
        if atts:
            item["attachments"] = atts
        items.append(item)
    return json.dumps(items, ensure_ascii=False, indent=2) + "\n"


def unique_slug(db: Session, base: str, exclude_id: int = None) -> str:
    base = re.sub(r"[\s/\\?#%]+", "-", _slugify(base)).strip("-")[:120] or "resource"
    slug, i = base, 2
    while True:
        q = db.query(Resource).filter(Resource.slug == slug)
        if exclude_id:
            q = q.filter(Resource.id != exclude_id)
        if q.first() is None:
            return slug
        slug, i = f"{base}-{i}", i + 1


def apply_resource(db: Session, r: Resource, body: ResourceIn) -> None:
    cat = db.query(Category).filter(Category.slug == body.category_slug).first()
    if not cat:
        raise HTTPException(status_code=422, detail="分类不存在")
    r.title = body.title.strip()
    r.slug = unique_slug(db, body.slug or body.title, exclude_id=r.id)
    r.category_id = cat.id
    r.category = cat
    r.description, r.content = body.description.strip(), body.content
    r.author, r.source = body.author.strip(), body.source.strip()
    r.difficulty, r.is_featured, r.status = body.difficulty, body.is_featured, body.status
    atts = [a.model_dump() for a in body.attachments]
    r.attachments = json.dumps(atts, ensure_ascii=False)
    r.file_type = body.file_type.strip() or (os.path.splitext(atts[0]["name"])[1][1:].upper() if atts else "")
    r.file_size = body.file_size.strip() or (human_size(sum(a["size"] for a in atts)) if atts else "")
    tags = []
    for name in dict.fromkeys(t.strip() for t in body.tag_names if t.strip()):
        tag = db.query(Tag).filter(Tag.name == name).first()
        if not tag:
            base, slug, i = _slugify(name), _slugify(name), 2
            while db.query(Tag).filter(Tag.slug == slug).first():
                slug, i = f"{base}-{i}", i + 1
            tag = Tag(name=name[:100], slug=slug)
            db.add(tag)
            db.flush()
        tags.append(tag)
    r.tags = tags
    r.updated_at = datetime.now(timezone.utc)


async def persist(db: Session, message: str) -> dict:
    """先把改动写入仓库 / 本地文件，成功后才提交数据库事务，保证两边一致。"""
    db.flush()
    try:
        result = await store.write_text(SEED_RESOURCES, export_resources(db), message)
    except ContentError as e:
        db.rollback()
        _fail(e)
    db.commit()
    return result


@router.get("/taxonomy")
def taxonomy(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "categories": [{"slug": c.slug, "name": c.name} for c in db.query(Category).order_by(Category.sort_order, Category.id)],
        "tags": sorted({t.name for t in db.query(Tag).all()}),
    }


@router.get("/resources")
def admin_resources(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [resource_out(r) for r in db.query(Resource).order_by(Resource.id.desc()).all()]


@router.get("/resources/{rid}")
def admin_resource(rid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(Resource, rid)
    if not r:
        raise HTTPException(status_code=404, detail="资源不存在")
    return resource_out(r, full=True)


@router.post("/resources")
async def create_resource(body: ResourceIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    store_check()
    r = Resource(title=body.title, slug="tmp", category_id=0)
    db.add(r)
    apply_resource(db, r, body)
    db.flush()
    await persist(db, f"content: 新增学习资源「{r.title}」（{admin.username} 通过管理后台）")
    return resource_out(r, full=True)


@router.put("/resources/{rid}")
async def update_resource(rid: int, body: ResourceIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    store_check()
    r = db.get(Resource, rid)
    if not r:
        raise HTTPException(status_code=404, detail="资源不存在")
    apply_resource(db, r, body)
    await persist(db, f"content: 更新学习资源「{r.title}」（{admin.username} 通过管理后台）")
    return resource_out(r, full=True)


@router.delete("/resources/{rid}")
async def delete_resource(rid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    store_check()
    r = db.get(Resource, rid)
    if not r:
        raise HTTPException(status_code=404, detail="资源不存在")
    title = r.title
    db.delete(r)
    await persist(db, f"content: 删除学习资源「{title}」（{admin.username} 通过管理后台）")
    return {"ok": True}


def store_check():
    try:
        store.require_writable()
    except ContentError as e:
        _fail(e)


async def attach_upload(db: Session, rid: int, file: UploadFile, admin: User) -> dict:
    """上传文件并追加为资源附件（旧版上传接口与后台共用）。"""
    store_check()
    r = db.get(Resource, rid)
    if not r:
        raise HTTPException(status_code=404, detail="资源不存在")
    name, data, ctype = await read_upload(file)
    try:
        item = await store.media_upload(name, data, ctype)
    except ContentError as e:
        _fail(e)
    atts = attachments_of(r) + [{"key": item["key"], "name": item["name"], "size": item["size"]}]
    r.attachments = json.dumps(atts, ensure_ascii=False)
    r.updated_at = datetime.now(timezone.utc)
    await persist(db, f"content: 为「{r.title}」上传附件 {name}（{admin.username} 通过管理后台）")
    return media_out(item)
