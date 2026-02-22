from __future__ import annotations

from typing import Optional

from .base import PyrusModel


class Attachment(PyrusModel):
    """A file attached to a task or comment."""

    id: int
    name: Optional[str] = None
    size: Optional[int] = None
    md5: Optional[str] = None
    url: Optional[str] = None
    root_id: Optional[int] = None
    version: Optional[int] = None


class UploadedFile(PyrusModel):
    """Response from POST /files/upload."""

    guid: str
    md5_hash: str
