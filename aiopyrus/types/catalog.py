from __future__ import annotations

from .base import PyrusModel


class CatalogHeader(PyrusModel):
    name: str
    type: str | None = None


class CatalogItem(PyrusModel):
    item_id: int
    values: list[str]
    deleted: bool | None = None


class Catalog(PyrusModel):
    """A Pyrus catalog (reference data table)."""

    catalog_id: int
    name: str
    version: int | None = None
    deleted: bool | None = None
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
    applied: bool | None = None
    added: list[CatalogItem] = []
    updated: list[CatalogItem] = []
    deleted: list[CatalogItem] = []
