"""Phase 2: Insert resources from JSON."""
import sys, json
sys.path.insert(0, ".")
from database import SessionLocal
from models import Category, Resource, Tag

db = SessionLocal()
cat_map = {c.slug: c for c in db.query(Category).all()}
tag_map = {t.name: t for t in db.query(Tag).all()}

with open("seed_resources.json", "r", encoding="utf-8") as f:
    resources = json.load(f)

for rd in resources:
    cat = cat_map[rd["category_slug"]]
    tag_objs = [tag_map[tn] for tn in rd.get("tag_names", []) if tn in tag_map]
    r = Resource(
        title=rd["title"], slug=rd["slug"], description=rd["description"],
        content=rd["content"], category_id=cat.id,
        author=rd.get("author",""), source=rd.get("source",""),
        file_type=rd.get("file_type",""), file_size=rd.get("file_size",""),
        difficulty=rd.get("difficulty",1), is_featured=rd.get("is_featured",False),
        tags=tag_objs,
    )
    db.add(r)

db.commit()
db.close()
print(f"Inserted {len(resources)} resources.")
