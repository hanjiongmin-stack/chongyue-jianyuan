"""Tag listing routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Tag, Resource, resource_tags
from schemas import TagOut

router = APIRouter(prefix="/api/v1/tags", tags=["tags"])


@router.get("", response_model=list[TagOut])
def list_tags(db: Session = Depends(get_db)):
    tags = db.query(Tag).order_by(Tag.name).all()
    result = []
    for tag in tags:
        count = db.query(func.count(resource_tags.c.resource_id)).filter(
            resource_tags.c.tag_id == tag.id
        ).scalar() or 0
        result.append(TagOut(
            id=tag.id,
            name=tag.name,
            slug=tag.slug,
            resource_count=count,
        ))
    return result


@router.get("/{slug}", response_model=TagOut)
def get_tag(slug: str, db: Session = Depends(get_db)):
    tag = db.query(Tag).filter(Tag.slug == slug).first()
    if not tag:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tag not found")
    count = db.query(func.count(resource_tags.c.resource_id)).filter(
        resource_tags.c.tag_id == tag.id
    ).scalar() or 0
    return TagOut(
        id=tag.id,
        name=tag.name,
        slug=tag.slug,
        resource_count=count,
    )
