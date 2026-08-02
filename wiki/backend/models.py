from typing import Optional
from pydantic import BaseModel, Field


class PageSummary(BaseModel):
    slug: str
    title: str
    category: str
    updated_at: str
    updated_by: str


class PageDetail(PageSummary):
    content: str
    created_at: str


class PageCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(default="Общее", max_length=100)
    content: str = ""
    slug: Optional[str] = Field(default=None, max_length=200)
    editor_name: str = Field(default="", max_length=100)


class PageUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    content: Optional[str] = None
    editor_name: str = Field(default="", max_length=100)
    comment: str = Field(default="", max_length=300)


class RevisionSummary(BaseModel):
    id: int
    edited_by: str
    edited_at: str
    title: str
    comment: str


class RevisionDetail(RevisionSummary):
    content: str
