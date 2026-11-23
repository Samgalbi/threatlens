"""Typed records flowing through the ingestion pipeline."""

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "technique",
    "mitigation",
    "group",
    "software",
    "campaign",
    "procedure",
    "capec",
    "cwe",
]


class SourceDocument(BaseModel):
    """One knowledge object (ATT&CK object, procedure example, CAPEC or CWE entry)."""

    doc_id: str = Field(min_length=1)  # STIX id or CWE-<n>
    external_id: str  # T1059.001, M1042, G0090, S0154, CAPEC-66, CWE-79
    name: str
    category: Category
    source: str  # e.g. "mitre-attack-enterprise v20.1"
    url: str | None = None
    date: str | None = None  # ISO date of last modification
    tactics: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    is_subtechnique: bool = False
    related_ids: list[str] = Field(default_factory=list)  # linked T####, CWE, CAPEC, G/S ids
    text: str  # cleaned body


class Chunk(BaseModel):
    """One indexed unit: a document or a slice of it, with its Qdrant payload."""

    point_id: str  # deterministic UUID5
    doc_id: str
    page: int = Field(ge=1)  # slice rank inside the document (1..n)
    total_pages: int = Field(ge=1)
    content: str
    payload: dict[str, object]
