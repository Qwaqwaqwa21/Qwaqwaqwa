"""Petrophysics internal wiki — standalone FastAPI app.

Runs as its own service on its own port with its own SQLite database.
Deliberately has zero imports from, or references to, the GeoLog
backend/frontend: it can be deployed, versioned, and moved to its own
repository without touching GeoLog at all.
"""
import re
import unicodedata
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from .database import db_session, init_db
from .models import PageCreate, PageDetail, PageSummary, PageUpdate, RevisionDetail, RevisionSummary
from .seed import SEED_PAGES

app = FastAPI(title="Petrophysics Wiki", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2}


def require_role(min_role: str):
    def _dep(x_role: str = Header(default="viewer")) -> str:
        role = x_role.lower().strip()
        if role not in ROLE_RANK:
            role = "viewer"
        if ROLE_RANK[role] < ROLE_RANK[min_role]:
            raise HTTPException(status_code=403, detail=f"Требуется роль '{min_role}' или выше")
        return role

    return _dep


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
        "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    lowered = text.lower()
    out = "".join(translit.get(ch, ch) for ch in lowered)
    out = re.sub(r"[^a-z0-9]+", "-", out).strip("-")
    return out or "page"


def unique_slug(conn, base: str) -> str:
    slug = base
    n = 2
    while conn.execute("SELECT 1 FROM pages WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug


@app.on_event("startup")
def on_startup():
    init_db()
    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM pages").fetchone()["c"]
        if count == 0:
            for p in SEED_PAGES:
                conn.execute(
                    "INSERT INTO pages (slug, title, category, content, updated_by) VALUES (?, ?, ?, ?, ?)",
                    (p["slug"], p["title"], p["category"], p["content"], "system"),
                )


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/categories", response_model=List[str])
def list_categories():
    with db_session() as conn:
        rows = conn.execute("SELECT DISTINCT category FROM pages ORDER BY category").fetchall()
        return [r["category"] for r in rows]


@app.get("/api/pages", response_model=List[PageSummary])
def list_pages(q: Optional[str] = None, category: Optional[str] = None):
    with db_session() as conn:
        sql = "SELECT slug, title, category, updated_at, updated_by FROM pages WHERE 1=1"
        params: list = []
        if q:
            sql += " AND (title LIKE ? OR content LIKE ?)"
            like = f"%{q}%"
            params += [like, like]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY category, title"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/pages/{slug}", response_model=PageDetail)
def get_page(slug: str):
    with db_session() as conn:
        row = conn.execute("SELECT * FROM pages WHERE slug = ?", (slug,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Страница не найдена")
        return dict(row)


@app.post("/api/pages", response_model=PageDetail)
def create_page(body: PageCreate, role: str = Depends(require_role("editor"))):
    with db_session() as conn:
        base = slugify(body.slug or body.title)
        slug = unique_slug(conn, base)
        conn.execute(
            "INSERT INTO pages (slug, title, category, content, updated_by) VALUES (?, ?, ?, ?, ?)",
            (slug, body.title, body.category, body.content, body.editor_name or "аноним"),
        )
        row = conn.execute("SELECT * FROM pages WHERE slug = ?", (slug,)).fetchone()
        return dict(row)


@app.put("/api/pages/{slug}", response_model=PageDetail)
def update_page(slug: str, body: PageUpdate, role: str = Depends(require_role("editor"))):
    with db_session() as conn:
        row = conn.execute("SELECT * FROM pages WHERE slug = ?", (slug,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Страница не найдена")

        conn.execute(
            "INSERT INTO revisions (page_id, title, content, edited_by, comment) VALUES (?, ?, ?, ?, ?)",
            (row["id"], row["title"], row["content"], body.editor_name or "аноним", body.comment),
        )

        new_title = body.title if body.title is not None else row["title"]
        new_category = body.category if body.category is not None else row["category"]
        new_content = body.content if body.content is not None else row["content"]
        conn.execute(
            "UPDATE pages SET title = ?, category = ?, content = ?, updated_at = datetime('now'), updated_by = ? WHERE id = ?",
            (new_title, new_category, new_content, body.editor_name or "аноним", row["id"]),
        )
        updated = conn.execute("SELECT * FROM pages WHERE id = ?", (row["id"],)).fetchone()
        return dict(updated)


@app.delete("/api/pages/{slug}")
def delete_page(slug: str, role: str = Depends(require_role("admin"))):
    with db_session() as conn:
        row = conn.execute("SELECT id FROM pages WHERE slug = ?", (slug,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Страница не найдена")
        conn.execute("DELETE FROM pages WHERE id = ?", (row["id"],))
        return {"deleted": slug}


@app.get("/api/pages/{slug}/history", response_model=List[RevisionSummary])
def page_history(slug: str):
    with db_session() as conn:
        page = conn.execute("SELECT id FROM pages WHERE slug = ?", (slug,)).fetchone()
        if not page:
            raise HTTPException(status_code=404, detail="Страница не найдена")
        rows = conn.execute(
            "SELECT id, edited_by, edited_at, title, comment FROM revisions WHERE page_id = ? ORDER BY edited_at DESC, id DESC",
            (page["id"],),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/pages/{slug}/history/{revision_id}", response_model=RevisionDetail)
def get_revision(slug: str, revision_id: int):
    with db_session() as conn:
        page = conn.execute("SELECT id FROM pages WHERE slug = ?", (slug,)).fetchone()
        if not page:
            raise HTTPException(status_code=404, detail="Страница не найдена")
        rev = conn.execute(
            "SELECT id, edited_by, edited_at, title, comment, content FROM revisions WHERE id = ? AND page_id = ?",
            (revision_id, page["id"]),
        ).fetchone()
        if not rev:
            raise HTTPException(status_code=404, detail="Версия не найдена")
        return dict(rev)


@app.post("/api/pages/{slug}/revert/{revision_id}", response_model=PageDetail)
def revert_page(slug: str, revision_id: int, editor_name: str = "", role: str = Depends(require_role("editor"))):
    with db_session() as conn:
        page = conn.execute("SELECT * FROM pages WHERE slug = ?", (slug,)).fetchone()
        if not page:
            raise HTTPException(status_code=404, detail="Страница не найдена")
        rev = conn.execute(
            "SELECT * FROM revisions WHERE id = ? AND page_id = ?", (revision_id, page["id"])
        ).fetchone()
        if not rev:
            raise HTTPException(status_code=404, detail="Версия не найдена")

        conn.execute(
            "INSERT INTO revisions (page_id, title, content, edited_by, comment) VALUES (?, ?, ?, ?, ?)",
            (page["id"], page["title"], page["content"], editor_name or "аноним", f"откат к версии #{revision_id}"),
        )
        conn.execute(
            "UPDATE pages SET title = ?, content = ?, updated_at = datetime('now'), updated_by = ? WHERE id = ?",
            (rev["title"], rev["content"], editor_name or "аноним", page["id"]),
        )
        updated = conn.execute("SELECT * FROM pages WHERE id = ?", (page["id"],)).fetchone()
        return dict(updated)


_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(_frontend_dir, "index.html"))
