"""Shared schema building blocks."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class NotImplementedNotice(BaseModel):
    """Returned instead of inventing a result.

    Used where a module's intelligence is not built yet. An endpoint that
    cannot do its job says so; it does not return a plausible placeholder.
    """

    implemented: bool = False
    module: str
    capability: str
    phase_planned: str
    detail: str
    blocking_dependency: str | None = None


class ProvenanceNote(BaseModel):
    provenance: str = Field(description="Origin of the values in this response")
    detail: str | None = None
