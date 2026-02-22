from __future__ import annotations

from typing import Optional

from .base import PyrusModel


class CatalogHeader(PyrusModel):
    name: str
    type: Optional[str] = None


class CatalogItem(PyrusModel):
    item_id: int
    values: list[str]
    deleted: Optional[bool] = None


class Catalog(PyrusModel):
    """A Pyrus catalog (reference data table)."""

    catalog_id: int
    name: str
    version: Optional[int] = None
    deleted: Optional[bool] = None
    catalog_headers: list[CatalogHeader] = []
    items: list[CatalogItem] = []

    def find_item(self, key: str) -> CatalogItem | None:
        """Find an item by its first-column value (the key)."""
        for item in self.items:
            if item.values and item.values[0] == key:
                return item
        return None


class CatalogSyncResult(PyrusModel):
    """Response from POST /catalogs/{id} or POST /catalogs/{id}/diff."""

    catalog_id: int
    applied: Optional[bool] = None
    added: list[CatalogItem] = []
    updated: list[CatalogItem] = []
    deleted: list[CatalogItem] = []
