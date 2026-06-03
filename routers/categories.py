"""Category listing routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Category, Resource
from schemas import CategoryOut

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    categories = (
        db.query(Category)
        .order_by(Category.sort_order)
        .all()
    )
    result = []
    for cat in categories:
        count = db.query(func.count(Resource.id)).filter(
            Resource.category_id == cat.id,
            Resource.status == "published"
        ).scalar() or 0
        result.append(CategoryOut(
            id=cat.id,
            name=cat.name,
            slug=cat.slug,
            description=cat.description or "",
            icon=cat.icon or "",
            sort_order=cat.sort_order or 0,
            resource_count=count,
        ))
    return result


@router.get("/{slug}", response_model=CategoryOut)
def get_category(slug: str, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.slug == slug).first()
    if not cat:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Category not found")
    count = db.query(func.count(Resource.id)).filter(
        Resource.category_id == cat.id,
        Resource.status == "published"
    ).scalar() or 0
    return CategoryOut(
        id=cat.id,
        name=cat.name,
        slug=cat.slug,
        description=cat.description or "",
        icon=cat.icon or "",
        sort_order=cat.sort_order or 0,
        resource_count=count,
    )
