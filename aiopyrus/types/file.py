from __future__ import annotations

from .base import PyrusModel


class Attachment(PyrusModel):
    """A file attached to a task or comment."""

    id: int
    name: str | None = None
    size: int | None = None
    md5: str | None = None
    url: str | None = None
    root_id: int | None = None
    version: int | None = None


class UploadedFile(PyrusModel):
    """Response from POST /files/upload."""

    guid: str
    md5_hash: str
