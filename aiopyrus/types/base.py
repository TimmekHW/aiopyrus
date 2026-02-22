from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PyrusModel(BaseModel):
    """Base model for all Pyrus API entities.

    Ignores extra fields from API responses to stay forward-compatible.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)
