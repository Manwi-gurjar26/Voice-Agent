from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings


class DocumentCreateText(BaseModel):
    source_type: Literal["text"] = "text"
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def _within_size_cap(cls, value: str) -> str:
        # Reject rather than truncate: silently cutting off the tail of a
        # pasted document would lose content the user has no way to notice
        # went missing.
        if len(value) > settings.max_pasted_text_chars:
            raise ValueError(
                f"content must be at most {settings.max_pasted_text_chars} characters"
            )
        return value


class DocumentCreateUrl(BaseModel):
    source_type: Literal["url"] = "url"
    # Optional: if omitted, derived from the page's <title> at fetch time.
    title: str | None = Field(default=None, max_length=300)
    url: str = Field(min_length=1, max_length=2048)


DocumentCreate = Annotated[
    Union[DocumentCreateText, DocumentCreateUrl], Field(discriminator="source_type")
]


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: str
    title: str
    source_url: str | None
    original_filename: str | None
    status: str
    error_message: str | None
    char_count: int | None
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentRead]
