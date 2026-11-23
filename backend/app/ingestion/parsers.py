"""Parsers for heterogeneous sources: ATT&CK STIX 2.1 (JSON), CAPEC STIX (JSON), CWE (XML)."""

import json
import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.ingestion.cleaning import clean_text
from app.ingestion.models import Category, SourceDocument

logger = logging.getLogger(__name__)

ATTACK_TYPES: dict[str, Category] = {
    "attack-pattern": "technique",
    "course-of-action": "mitigation",
    "intrusion-set": "group",
    "malware": "software",
    "tool": "software",
    "campaign": "campaign",
}


def _is_active(obj: dict[str, Any]) -> bool:
    return not obj.get("revoked", False) and not obj.get("x_mitre_deprecated", False)


def _attack_ref(obj: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (external_id, url) from the 'mitre-attack' external reference."""
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack" and ref.get("external_id"):
            return ref["external_id"], ref.get("url")
    return None, None


def load_stix_objects(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        bundle = json.load(f)
    objects = bundle.get("objects", [])
    if not isinstance(objects, list):
        raise ValueError(f"{path}: not a STIX bundle (no 'objects' list)")
    return objects


def attack_version(objects: list[dict[str, Any]]) -> str:
    for obj in objects:
        if obj.get("type") == "x-mitre-collection":
            return str(obj.get("x_mitre_version", "unknown"))
    return "unknown"


def parse_attack(objects: list[dict[str, Any]]) -> Iterator[SourceDocument]:
    """Yield ATT&CK entities, then one document per procedure example ('uses' + description)."""
    source = f"mitre-attack-enterprise v{attack_version(objects)}"
    by_id = {o["id"]: o for o in objects if "id" in o}
    skipped = 0

    for obj in objects:
        category = ATTACK_TYPES.get(obj.get("type", ""))
        if category is None or not _is_active(obj):
            continue
        external_id, url = _attack_ref(obj)
        if external_id is None:
            skipped += 1
            continue
        tactics = [
            p["phase_name"]
            for p in obj.get("kill_chain_phases", [])
            if p.get("kill_chain_name") == "mitre-attack"
        ]
        yield SourceDocument(
            doc_id=obj["id"],
            external_id=external_id,
            name=obj.get("name", external_id),
            category=category,
            source=source,
            url=url,
            date=(obj.get("modified") or "")[:10] or None,
            tactics=tactics,
            platforms=obj.get("x_mitre_platforms", []),
            is_subtechnique=bool(obj.get("x_mitre_is_subtechnique", False)),
            text=clean_text(obj.get("description")),
        )

    for rel in objects:
        if rel.get("type") != "relationship" or rel.get("relationship_type") != "uses":
            continue
        if not _is_active(rel) or not rel.get("description"):
            continue
        src, tgt = by_id.get(rel.get("source_ref", "")), by_id.get(rel.get("target_ref", ""))
        if not src or not tgt or tgt.get("type") != "attack-pattern":
            continue
        if not (_is_active(src) and _is_active(tgt)):
            continue
        src_id, _ = _attack_ref(src)
        tgt_id, tgt_url = _attack_ref(tgt)
        if not src_id or not tgt_id:
            skipped += 1
            continue
        yield SourceDocument(
            doc_id=rel["id"],
            external_id=tgt_id,  # filter "all procedures of T1059.001"
            name=f"{src.get('name')} -> {tgt.get('name')}",
            category="procedure",
            source=source,
            url=tgt_url,
            date=(rel.get("modified") or "")[:10] or None,
            tactics=[
                p["phase_name"]
                for p in tgt.get("kill_chain_phases", [])
                if p.get("kill_chain_name") == "mitre-attack"
            ],
            platforms=tgt.get("x_mitre_platforms", []),
            is_subtechnique=bool(tgt.get("x_mitre_is_subtechnique", False)),
            related_ids=[src_id, tgt_id],
            text=clean_text(rel["description"]),
        )
    if skipped:
        logger.warning("ATT&CK: %d objects skipped (no mitre-attack external id)", skipped)


def parse_capec(objects: list[dict[str, Any]]) -> Iterator[SourceDocument]:
    """Yield CAPEC attack patterns with their CWE and ATT&CK links (the CWE <-> ATT&CK bridge)."""
    for obj in objects:
        if obj.get("type") != "attack-pattern" or obj.get("revoked"):
            continue
        if obj.get("x_capec_status") in {"Deprecated", "Obsolete"}:
            continue
        refs = obj.get("external_references", [])
        capec = next((r for r in refs if r.get("source_name") == "capec"), None)
        if capec is None:
            continue
        related: list[str] = []
        for r in refs:
            eid = str(r.get("external_id", ""))
            if r.get("source_name") == "cwe" and eid:
                related.append(eid)
            elif r.get("source_name") == "ATTACK" and eid:
                related.append(eid if eid.startswith("T") else f"T{eid}")
        yield SourceDocument(
            doc_id=obj["id"],
            external_id=capec["external_id"],
            name=obj.get("name", capec["external_id"]),
            category="capec",
            source=f"capec v{obj.get('x_capec_version', 'unknown')}",
            url=capec.get("url"),
            date=(obj.get("modified") or "")[:10] or None,
            related_ids=related,
            text=clean_text(obj.get("description")),
        )


def _local(tag: str) -> str:
    """Strip the XML namespace: '{http://cwe.mitre.org/cwe-7}Weakness' -> 'Weakness'."""
    return tag.rsplit("}", 1)[-1]


def _child_text(elem: ET.Element, name: str) -> str:
    for child in elem:
        if _local(child.tag) == name:
            return " ".join("".join(child.itertext()).split())
    return ""


def parse_cwe(path: Path) -> Iterator[SourceDocument]:
    """Yield CWE weaknesses from the official XML catalogue (namespace-agnostic)."""
    root = ET.parse(path).getroot()
    source = f"cwe v{root.get('Version', 'unknown')}"
    date = root.get("Date")
    for elem in root.iter():
        if _local(elem.tag) != "Weakness":
            continue
        if elem.get("Status") in {"Deprecated", "Obsolete"}:
            continue
        cwe_id = f"CWE-{elem.get('ID')}"
        description = _child_text(elem, "Description")
        extended = _child_text(elem, "Extended_Description")
        text = clean_text(f"{description}\n\n{extended}" if extended else description)
        if not text:
            continue
        yield SourceDocument(
            doc_id=cwe_id,
            external_id=cwe_id,
            name=elem.get("Name", cwe_id),
            category="cwe",
            source=source,
            url=f"https://cwe.mitre.org/data/definitions/{elem.get('ID')}.html",
            date=date,
            text=text,
        )
